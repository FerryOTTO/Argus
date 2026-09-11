# Audit 模块

## 1. 模块职责

Audit 模块接收并保存 Clawguard 全链路产生的统一 `AuditEvent`，按 `trace_id`
派生任务图，并提供节点、Trace、筛选、原因路径和影响路径的 Python 查询能力。

它不是风险检测器，也不参与阻断。正式风险的 `action`、`risk_score` 和 `reason`
来自 IO Guard、Tool Guard 等上游安全模块；Audit 只原样保存并按配置阈值选择溯源起点。


## 2. 数据流

```text
POST /v1/audit/event
  → 团队公共 AuditEvent 校验
  → SecurityRequest(stage="audit")
  → AuditAdapter.run()
  → original.record_audit_event()
  → runtime/audit/audit-events.jsonl
  → AuditQuery 按 trace 派生 NetworkX MultiDiGraph
```

输入和输出安全结果由统一编排层自动写入 Audit，包括被拦截的输入和被重写或拦截的
输出：

```text
POST /v1/input/check  → IO Guard Input ModuleResult  → AuditAdapter → JSONL
POST /v1/output/check → IO Guard Output ModuleResult → AuditAdapter → JSONL
```

两条接口均先保留原安全判断，再以旁路方式尝试写入审计；Audit 写入失败不会改变
`allow`、`block`、`rewrite` 或 `human_review` 的原始响应。

访问控制和工具安全运行结果还会由统一编排层在进程内自动写入 Audit：

```text
POST /v1/tool/pre_check
  → AccessControlAdapter
  → Access Control ModuleResult → AuditAdapter → JSONL
  → Access allow 时运行 ToolGuardAdapter
  → Tool Guard ModuleResult → AuditAdapter → JSONL
  → Audit 查询 API 与 /audit 页面
```

Access Control block 会先记录 Access 结果，再直接返回且不运行 Tool Guard。Access
allow 会依次记录 Access 与 Tool Guard 的原始结果。allow、block、human_review 和模块
异常结果都会尝试记录；Audit 失败不会改变安全结果、不会让接口返回 500，也不会把
Audit 的 `ModuleResult` 加入原安全响应。

检索内容检查也由统一编排层自动写入 Audit：

```text
POST /v1/content/check
  → Retrieval Guard ModuleResult → AuditAdapter → JSONL
  → 可选 IO Guard Context ModuleResult → AuditAdapter → JSONL
  → Audit 查询 API 与 /audit 页面
```

两个内容检查事件共用原请求的 trace、session、user 和 `tool_call_id`。存在相同
`trace_id + tool_call_id` 的工具前检查事件时，Retrieval Guard 事件指向最后一条匹配的
`tool_pre` 事件；IO Guard Context 事件指向本次真实写入成功的 Retrieval Guard 事件。
找不到匹配事件或 Audit 写入失败时不伪造 parent。Audit 仅记录模块现有返回，不修改
Retrieval Guard、IO Guard Context 的规则、阈值、模型、动作或公共安全响应。

本模块复用团队已有 FastAPI，不启动第二个服务，不通过 subprocess 调 CLI，也不修改
`sys.path`。`AuditAdapter` 延迟导入 `original`，写入异常统一转换为
`success=false`、`action=allow`、`reason=audit_write_error`，不会阻断主流程。

## 3. AuditEvent 字段

| 字段 | 含义 |
|---|---|
| `event_id` | 全局事件标识；节点查询键 |
| `trace_id` | 任务图隔离键；不同 trace 永不合图 |
| `session_id` / `user_id` | 查询条件，不替代 trace |
| `timestamp` | 带时区的 ISO 8601 时间 |
| `stage` | 事件所处链路阶段 |
| `source_module` | 产生事件的安全模块 |
| `action` | 上游模块原始动作 |
| `risk_score` | 上游模块 0.0～1.0 原始分数 |
| `reason` | 上游模块原始原因文本 |
| `content` | 原始业务内容对象 |
| `metadata` | `parent_event_id`、`sequence` 等关联信息 |

不会生成 `high`、`critical` 等正式风险等级，也不会把分数转换为 0～100。

## 4. 配置

默认目录是仓库相对路径 `runtime/audit/`，默认文件为
`runtime/audit/audit-events.jsonl`。

```powershell
$env:CLAWGUARD_AUDIT_DIR = "runtime/audit"
$env:CLAWGUARD_AUDIT_PATH = "runtime/audit/custom.jsonl"
$env:CLAWGUARD_AUDIT_RISK_THRESHOLD = "0.5"
```

`CLAWGUARD_AUDIT_PATH` 优先于 `CLAWGUARD_AUDIT_DIR`。阈值必须位于 0～1；当
`risk_score >= threshold` 时事件标为 `direct_risk_source=true`。阈值只影响调查入口，
不会修改原始分数、原因或动作。

## 5. Access Control / Tool Guard 字段与幂等映射

两个模块的 `ModuleResult` 使用同一个映射器形成统一 `AuditEvent`：

- `trace_id`、`session_id`、`user_id`、`timestamp` 来自原 `SecurityRequest.context`；
- `stage` 保留原工具前检查阶段 `tool_pre`；
- `source_module`、`action`、`risk_score`、`reason` 来自真实 `ModuleResult`；
- `content` 保存规范化 `tool_name`、`original_tool_name`（存在时）、`arguments`，以及
  Access Control 已返回的 `path`、`database`；
- `metadata` 保存原始 `details`、`tool_call_id`、`module_success`、`latency_ms`、`error`、
  请求摘要和关联质量；映射器会保留编排层传入的 `parent_event_id` 和最终
  AuditEvent `sequence`。

同一次 `/v1/tool/pre_check` 中，两个事件共用 trace、session、user 和 tool call，事件
ID 不同。OpenClaw Adapter 为同一 Trace 的工具调用分配从 0 开始的递增编号 `n`，
统一入口将每次调用展开为四个不重复的事件槽位：Access `4n`、Tool Guard
`4n+1`、Retrieval Guard `4n+2`、IO Guard Context `4n+3`。Access 写入回执能安全
提供真实 `event_id` 时，Tool Guard 的 `parent_event_id` 指向它；Audit 写入失败或回执
没有 ID 时不伪造 parent。调用方没有提供合法非负调用编号时，不会默认
重用 0，而是省略 sequence 并明确降级为时间顺序推断。

`event_id` 使用 UUIDv5，由 trace、session、user、stage、模块、请求时间、
`tool_call_id`、规范化请求摘要和显式关联字段共同确定。相同请求重放得到相同 ID；
不同 `tool_call_id` 得到不同 ID。真实运行耗时会随重试波动，因此当已有事件除
`latency_ms` 外完全一致时复用第一次记录的正文；其他差异仍由 AuditStore 的冲突保护
拒绝，不覆盖原记录。

缺少 `tool_call_id` 时，以稳定请求摘要作为 fallback，并记录
`correlation_quality="fallback"`。这种情况下，同一 trace、同一请求时间且内容完全相同
的两次独立工具调用无法区分；调用方应尽可能提供真实 `tool_call_id`。缺少显式 parent
和 sequence 时不会伪造确定因果，派生图只能建立带 `temporal_sequence` 标记的时序边。

内容检查事件使用同一映射器，并在 `content` 中保存 `tool_name`、`source`、`url`、
`tool_call_id` 及本次送检的 `content`/`text`。模块返回的 `modified_data` 原样保存在
`metadata.modified_data`，其余成功状态、明细、耗时和错误沿用上述映射。本地 MVP 当前
不做脱敏，因此只能使用非敏感数据，JSONL 仍是原始事实源。

输入和输出事件在 `content` 中保留统一接口收到的原始业务 payload，例如 `text`、
`channel`、`purpose` 和调用方 metadata；安全模块产生的改写结果仍保存在
`metadata.modified_data`。未提供显式 parent 或 sequence 时按 fallback 关联，不伪造
确定因果。

## 6. 图完整性

- 首先按 `trace_id` 分图；跨 trace 输入不能构成一张图；
- 优先使用 `metadata.parent_event_id`，并保留 `metadata.sequence`；
- 无显式 parent 时按 sequence、绝对时间和 `event_id` 稳定排序，建立
  `inference="temporal_sequence"` 的时序边；
- 时序边只表示先后，不声明确定因果；
- 重复 `event_id`、缺失父节点或有向循环抛出 `GraphIntegrityError`，不静默修补。

## 7. Python 查询

```python
from clawguard.modules.audit.original import AuditQuery

query = AuditQuery()
event = query.get_event("event-001")
trace = query.get_trace("trace-001")
traces = query.list_traces(session_id="session-001")
risks = query.direct_risk_sources(source_module="tool_guard")
causes = query.causes("risk-event", max_depth=8, max_paths=10)
impacts = query.impacts("risk-event", max_depth=8, max_paths=10)
```

`events()` 还支持 `trace_id`、`session_id`、`source_module`、`stage`、
`risk_score_min` 和 `direct_risk_sources_only`。路径结果是结构化 JSON 兼容对象，包含
节点、边、`relation`、边证据 `event_id`、`timestamp` 和可选 `inference`。
PNG 不是必需调查方式，本模块不自动生成图片或图文件。

## 8. 动态审计页面

动态页面复用团队统一 FastAPI；不会启动第二个服务，也不需要 Node、React、Vue、
Streamlit、Gradio 或外部 CDN。

```powershell
.\.venv\Scripts\python.exe -m uvicorn clawguard.api.main:app --host 127.0.0.1 --port 8000
```

启动后访问：

- 页面：`http://127.0.0.1:8000/audit`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

正式页面采用 Audit UI V2 的概览、Trace 工作台、Timeline/Graph 双视图和 Event Drawer。
页面只通过 Audit 查询 API 按需读取真实数据，不内置演示 Trace，也不会在请求失败或空
日志时回退到 synthetic 数据。Overview KPI 和图表来自全局 `/v1/audit/overview` 聚合；
工作台搜索、Session、模块、动作和风险筛选只影响工作区，不会反向改变全局 KPI。

页面每 5 秒自动刷新；当前 Trace 仍存在时继续刷新其 Detail，并尽量保留当前 Trace、
Event、Timeline/Graph 模式、Drawer、折叠项、筛选、Theme 和图路径模式。自动刷新不会
重新播放 Trace；Replay 只在首次选择或主动切换 Trace 时启动，每步间隔 175ms。单次
请求失败时保留上一次成功数据、关闭绿色在线状态并显示错误，不会把页面整体清空。

Event Drawer 展示完整统一 `AuditEvent`、父子事件和 API 返回的入出边。`content`、
`metadata` 及原始 JSON 默认独立折叠。只有 `direct_risk_source=true` 的事件可以发起
“查原因”和“查影响”；底层直接调用 `AuditQuery.causes()` 和 `AuditQuery.impacts()`，
页面不复制 BFS。确定受影响节点只沿明确 `PARENT_OF` 后代派生；经过
`temporal_sequence` 的节点只显示“可能受影响 / 时序关联”。

链路完整率定义为 `confirmed_edge_count / (confirmed_edge_count +
temporal_edge_count)`；全局没有任何边时按 100% 处理。风险趋势按直接风险源事件的真实
UTC 日期分桶，模块分布按真实 `source_module` 计数，不补点、不平滑。


## 9. 查询接口

| 方法与路径 | 用途 |
|---|---|
| `GET /v1/audit/overview` | 全局事件、风险、动作、边完整率、真实风险趋势和模块分布 |
| `GET /v1/audit/traces` | 最新优先的 Trace 摘要；支持 `session_id`、`risk_only`、`limit`、`offset` |
| `GET /v1/audit/traces/{trace_id}` | 稳定排序的任务节点、关系边和风险数量 |
| `GET /v1/audit/events/{event_id}` | 完整事件、直接风险标记、父子节点和入出边 |
| `GET /v1/audit/events/{event_id}/causes` | 有界原因路径；支持 `max_depth`、`max_paths` |
| `GET /v1/audit/events/{event_id}/impacts` | 有界影响路径；支持 `max_depth`、`max_paths` |
| `GET /audit` | 原生 HTML/CSS/JavaScript 动态页面 |


## 10. 安装和测试

```powershell
python -m pip install -r requirements.txt
python -m pip install -r clawguard/modules/audit/requirements.txt
python -m pytest tests/test_audit_adapter.py tests/test_audit_graph.py tests/test_audit_api.py tests/test_audit_ui.py tests/test_audit_access_control_integration.py tests/test_audit_content_integration.py -q
python -m pytest -q
python -m compileall -q clawguard tests
python -m pip check
git diff --check
```

测试夹具均为人工构造的内容，位于 `tests/fixtures/audit/`。
