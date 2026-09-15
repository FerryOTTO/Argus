# Phase 6 Audit 动态审计界面验收报告

## 1. 实现内容

Phase 6 在团队统一 FastAPI 中增加 Audit 只读 Router 和原生 HTML/CSS/JavaScript
页面。数据仍以 JSONL 为事实源，经 `AuditQuery` 和 NetworkX 派生图完成查询；页面只把
任务、事件、父子关系和溯源路径转换成文字视图，不展示整张关系图。

`argus/api/main.py` 只增加 Audit Router 的导入和 `include_router()` 注册。查询、
错误映射和页面入口位于 `argus/api/audit_routes.py`，没有把 Audit 业务逻辑写入
`main.py`。

## 2. 只读接口

| 接口 | 结果 |
|---|---|
| `GET /v1/audit/traces` | 最新优先的 Trace 摘要、Session/风险筛选和有界分页 |
| `GET /v1/audit/traces/{trace_id}` | 单 Trace 的稳定排序节点、边、风险数和时间范围 |
| `GET /v1/audit/events/{event_id}` | 完整 AuditEvent、风险标记、父子事件及入出边 |
| `GET /v1/audit/events/{event_id}/causes` | 直接复用 `AuditQuery.causes()` |
| `GET /v1/audit/events/{event_id}/impacts` | 直接复用 `AuditQuery.impacts()` |
| `GET /audit` | 无外部依赖的动态审计页面 |

新增 Router 没有 PUT、PATCH、POST 或 DELETE。已有 `POST /v1/audit/event` 保持不变。

## 3. 页面交互

- 三栏分别显示任务列表、事件时间线和事件详情；
- 支持 Trace/Event 关键词、Session、风险任务筛选和手动刷新；
- 每 5 秒重新读取任务列表和当前 Trace，使用服务端结果替换视图，不累加重复事件；
- 自动刷新尽量保留选中的 Trace、Event 和已打开的路径；
- 请求失败时显示错误并保留上一次成功数据；
- 风险任务和直接风险事件有明确文字标识，不只依赖颜色；
- `content`、`metadata` 和完整 AuditEvent JSON 默认折叠；
- 父事件、子事件和路径事件均可点击跳转；
- 原因和影响使用文字步骤展示；
- `temporal_sequence` 明确显示为时间顺序推断，不描述为确定因果。

## 4. 测试结果

本阶段定向测试覆盖原有 Audit、API 和 UI，共 50 项：

```text
50 passed, 1 warning
```

团队完整回归结果：

```text
169 passed, 5 skipped, 1 warning, 2 subtests passed
```

唯一 warning 为已有 FastAPI TestClient/Starlette 弃用提示，没有测试失败。

API 测试覆盖空日志、Trace 列表与分页、风险筛选、Trace 隔离、Event 邻接关系、
causes/impacts、非风险事件错误、404、非法参数、损坏 JSONL 安全错误、图完整性错误和
查询前后 SHA-256 不变。UI 测试覆盖三栏、筛选、路径按钮、5 秒轮询、状态保留文案、
空/加载/错误状态、时序免责声明及无外部 CDN。

## 5. 人工验收

使用 `tests/fixtures/audit/phase6_events.synthetic.jsonl` 中 10 条人工非敏感事件，通过
现有 `POST /v1/audit/event` 写入本机已忽略的 runtime JSONL：

- 普通任务：3 个事件，0 个直接风险事件，明确父关系；
- 风险任务：4 个事件，1 个直接风险事件，原因和影响均有结果；
- 时序任务：3 个事件，2 条 `temporal_sequence` 边。

实际启动统一 Uvicorn 后，`/health`、`/docs`、`/audit` 均返回 HTTP 200。浏览器检查
确认三栏渲染、Trace/Event 点击、父子关系、原因路径、影响路径、路径节点跳转、风险
筛选和时序提示正常。等待一次 5 秒轮询后，当前风险 Trace 仍为 4 个事件，没有重复，
选中的事件和已打开路径均保留；控制台没有错误。只读查询前后 runtime JSONL 的
SHA-256 一致。

## 6. Git 与 PR

- 分支：`module/audit-ui`
- 实现提交：`9b9148151823baa65acaca7d1586aba400b71f1c`
- PR：`https://github.com/WT-ever/Argus/pull/10`（Draft）
- 不合并 PR，不修改旧 PR #5。

## 7. 当前限制

- 页面仅用于 `127.0.0.1` 本机的人工非敏感数据演示；
- 暂未接入 OpenGuard 权限系统；
- 没有数据库、WebSocket、外部前端资源或独立前端服务；
- 本阶段不实现脱敏，因此不能用于展示真实敏感数据；
- JSONL 仍是事实源，页面和查询接口不能修改事件或关系；
- runtime 日志和页面运行数据不提交 Git。
