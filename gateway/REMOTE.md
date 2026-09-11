# LLMGate 遥测/集控协议 — 客户端接入文档（REMOTE）

> **读者**：Argus 客户端工程师（终端侧 Agent 遥测客户端实现者）。
> **背景**：LLMGate 作为遥测/集控端（中央管理），对运行在各终端机器上的
> Agent 端点（OpenClaw + Argus）进行登记、监控与配置下发。本仓库已实现
> 服务端全部接口并预留数据模型；本文档即客户端与服务端的对接契约。
> 接口地址约定为 `<LLMGATE_BASE_URL>`，如 `http://gate.example.com:8080`。

---

## 1. 角色与整体时序

```
┌─────────────────────────┐        ┌──────────────────────────┐
│  终端（客户端实现方）     │        │  LLMGate（服务端，已实现） │
│  OpenClaw + Argus   │        │  遥测 API + 管理界面      │
└────────────┬────────────┘        └────────────┬─────────────┘
             │  ① 管理员在控制台"添加终端"          ▲
             │     获得一次性注册码(registration_code)
             │                                  │
             │  ② POST /telemetry/v1/register   │ 签发 per-terminal 遥测令牌
             │  ───────────────────────────────▶│ + 平台 LLM 凭据（均仅返回一次）
             │                                  │
             │  ③ POST /telemetry/v1/heartbeat  │ 周期性心跳（Bearer Token）
             │  ◀───────────────────────────────│ 响应含 config_pending 标志
             │                                  │
             │  ④ GET /telemetry/v1/config      │ 拉取集控下发的 Argus 配置
             │  ◀───────────────────────────────│ （仅在 config_pending=true 时）
             │  ⑤ 应用配置后 POST /telemetry/v1/config/applied（回执）
             │                                  │
             │  ⑥ POST /telemetry/v1/report     │ 上报 Token 消耗/安全预警增量
             │  ⑥a audit/events 审计明细        │ 批量上传 Argus 审计事件（幂等去重，见 §4.7）
             │                                  │
             │  ⑦ 用 llm.api_key 访问平台 LLM  │ OpenAI 兼容：{llm.base_url}/models
             │  ───────────────────────────────▶│ chat/completions …
             │                                  │
             │  ⑧ 令牌被吊销/过期(401) → 用注册码重新注册（步骤 ②）
```

**关键设计决策（与本实现一一对应）：**

| 决策点 | 结论 |
|--------|------|
| 配置下发 | **客户端轮询拉取**（无反向连接；管理员保存后 version+1，客户端心跳感知后拉取） |
| 扩展治理 | **skill/MCP 安装须审批、Skill 包集控分发**：审批默认人工（自动审批接口已预留，见 §11）；skill 分发与配置下发同构——拉取 + 回执（完整对接见 [CLIENT.md](./CLIENT.md)） |
| 鉴权 | **每终端独立 Token**；注册码换取令牌；库中只存哈希 |
| 终端 LLM | **平台签发 LLM API key 随注册下发**（企业名/base_url 由系统设置组合）；终端未绑定时签发“无主”key，绑定用户变更时 key 归属同步 |
| 运行数据 | **纯客户端上报聚合**（Token 消耗数、安全预警次数均为累计值） |
| 审计汇聚 | **客户端周期全量上报审计事件**（AuditEvent）；服务端按 (终端, event_id) 幂等去重落库，本地 JSONL 仍是权威副本 |

---

## 2. 认证与凭据

### 2.1 凭据形态

| 凭据 | 生成方 | 用途 | 有效期 |
|------|--------|------|--------|
| `registration_code` | LLMGate 控制台“添加终端/重置注册码” | 换取遥测令牌 | 长期有效（重新生成后旧码失效；吊销后作废） |
| `token` | 注册接口返回 | 心跳/上报/拉配置的 Bearer 鉴权 | 长期有效（吊销或重新注册后旧令牌立即失效） |
| `llm.api_key` | 注册接口返回（平台自动签发） | 该终端智能体的 LLM 接入：OpenAI 兼容 `{llm.base_url}`（`sk-…`） | 长期有效（吊销终端/停用密钥后失效；重复注册会轮换） |

`registration_code`/`token` 均为 64 位十六进制字符串。**令牌与 LLM 密钥明文仅在
注册响应中出现一次**，客户端需持久化保存于本地配置（如 `config/remote.json`）；
丢失后不可找回，只能由管理员重新生成注册码并重新走注册流程。

### 2.2 鉴权头

除注册接口外，所有遥测接口均需携带：

```
Authorization: Bearer <token>
```

失败返回 `401`（`code=invalid_telemetry_token`）：客户端应停止当前上报并尝试
用注册码重新注册（见 §8 异常处理）。重复 401 且重注册仍失败时，降级为离线
并在本地日志告警，等待管理员处理（可能已被吊销）。

---

## 3. API 一览

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| POST | `/telemetry/v1/register` | 注册码（body） | 换取遥测令牌 + 平台 LLM 凭据（可重复调用以轮换两者） |
| POST | `/telemetry/v1/heartbeat` | Bearer | 周期心跳 + 运行元数据上报 |
| GET | `/telemetry/v1/config` | Bearer | 拉取集控下发的 Argus 配置（幂等） |
| POST | `/telemetry/v1/config/applied` | Bearer | 应用配置成功后的回执 |
| POST | `/telemetry/v1/report` | Bearer | 上报用量/安全预警增量 |
| POST | `/telemetry/v1/audit/events` | Bearer | 批量上传 Argus 审计事件（全量，幂等去重） |
| POST | `/telemetry/v1/extensions/requests` | Bearer | 上报 skill 安装 / MCP 接入审批申请（契约见 [CLIENT.md](./CLIENT.md) §2） |
| GET | `/telemetry/v1/extensions/requests` | Bearer | 轮询本终端的审批单与结果（建议 30s/次直至非 pending） |
| GET | `/telemetry/v1/skills` | Bearer | 拉取分配给本终端的 Skill 包（zip base64 + 版本 + 回执状态） |
| POST | `/telemetry/v1/skills/applied` | Bearer | Skill 安装结果回执（ok/failed，版本语义见 CLIENT.md §3） |
| GET | `{base_url}/v1/models` | Bearer `llm.api_key` | 查询当前 key 可访问的模型列表（随注册下发的 LLM 凭据） |

> 管理端（控制台）接口见 §7，客户端通常不需要调用。
> 所有时间字段一律 ISO 8601 UTC（如 `2026-09-08T10:00:00Z`）。

**错误响应统一格式**：

```json
{ "error": { "message": "...", "type": "invalid_request_error | authentication_error | internal_error | not_found_error", "code": "可选细分码" } }
```

---

## 4. 接口明细

### 4.1 注册 `POST /telemetry/v1/register`

请求：

```json
{
  "registration_code": "<管理员下发的注册码>",
  "hostname": "zhangsan-macbook",
  "os_info": "macOS 26.5.1",
  "agent_type": "openclaw",
  "agent_version": "2026.6.11",
  "argus_version": "2.1.0"
}
```

字段说明：`agent_type` 必须与管理员创建终端时选择的类型一致（当前仅
`openclaw`），不一致返回 409；不传则视为不声明（按登记类型）。
`hostname/os_info/agent_version/argus_version` 均可选，注册后仍可经
心跳更新。

成功响应（`200`）：

```json
{
  "data": {
    "terminal_id": 1,
    "terminal_name": "研发-张三的MacBook",
    "agent_type": "openclaw",
    "token": "<64位遥测令牌，仅此一次>",
    "hint": "token and llm credentials are shown only once; store them in the client config",
    "skills_pending": false,
    "llm": {
      "api_key_id": 3,
      "api_key": "<sk-…平台签发的 LLM 密钥，仅此一次>",
      "base_url": "http://gate.example.com:8080/v1",
      "enterprise_name": "XX 科技有限公司"
    }
  }
}
```

`llm` 块说明：
- `api_key`：**仅此一次**返回，客户端应持久化；吊销终端或管理员停用该密钥后失效。
- `base_url` = 系统设置「系统根地址」+ `/v1`（未配置根地址时为空串）；
  LLM 请求用 OpenAI 兼容格式：`POST {base_url}/chat/completions`、`GET {base_url}/models`，
  鉴权头 `Authorization: Bearer <llm.api_key>`。
- `enterprise_name`：系统设置的企业名称（未配置时为空串），供客户端展示。
- 该 key 的模型访问范围 = 系统设置「开放模型」白名单（不配置/留空 = 全部模型），
  越权模型返回 403 `model_not_permitted`。

客户端行为：持久化 `token` 与 `llm`（key/base_url）并立即开始心跳；**重复调用会
使旧令牌与旧 LLM key 失效**（重新注册即轮换两者，用于凭据丢失后的恢复）。

`skills_pending`：注册完成即返回。`true` 表示本终端已有待安装的 Skill 包
（典型为管理员配置的“新终端默认包”刚完成分配），应立即按 [CLIENT.md](./CLIENT.md) §3
拉取并安装；`false` 则无需动作。

### 4.2 心跳 `POST /telemetry/v1/heartbeat`

请求：

```json
{
  "hostname": "zhangsan-macbook",
  "os_info": "macOS 26.5.1",
  "agent_type": "openclaw",
  "agent_version": "2026.6.11",
  "argus_version": "2.1.0"
}
```

全部字段可选；服务端对非空字段做更新，**空字段不覆盖**已有值。

成功响应：

```json
{
  "data": {
    "status": "ok",
    "server_time": "2026-09-08T10:00:00Z",
    "config_pending": true,
    "config_version": 3,
    "skills_pending": false
  }
}
```

`config_pending=true` 表示存在客户端尚未应用（回执）的配置版本 → 客户端应立即
执行 §4.3 拉取并应用；`false` 则无需动作。建议心跳周期 **30–60 秒**（服务端
以 120 秒未心跳判定离线；周期不要小于 30 秒，避免对服务端造成无谓压力）。

`skills_pending=true` 表示本终端存在尚未同步（最近回执非 ok 或版本落后）的 Skill 包
→ 应执行 [CLIENT.md](./CLIENT.md) §3 的拉取安装流程；`false` 则无需动作。

### 4.3 拉取配置 `GET /telemetry/v1/config`

响应：

```json
{
  "data": {
    "terminal_id": 1,
    "config_version": 3,
    "config": "{\"schema_version\":1,\"modules\":{\"io_guard_input\":{\"enabled\":false}}}",
    "config_updated_at": "2026-09-08T09:59:00Z",
    "config_pending": true,
    "config_applied_version": 2
  }
}
```

规则：

- `config` 为空字符串 = 集控从未下发或已收回 → 客户端**维持本地配置**。
- `config` 非空 = **Argus 配置包 v1**（JSON，结构见 §4.6）→ 客户端应：
  1. 校验 `schema_version`（≠ 客户端支持的版本 → 拒绝应用并本地告警，不回执）；
  2. 按 §4.6.2 合并规则将配置包 merge 到本地 Argus 配置（建议备份本地当前
     配置后原子替换，失败回滚）；
  3. 应用成功 → 调用 §4.4 回执该 `config_version`；
  4. 应用失败 → **不要回执**，记本地日志并告警（服务端仍显示 pending，
     管理员可据此重试/排查）。可周期性（如每 5 分钟）重试。

### 4.4 应用回执 `POST /telemetry/v1/config/applied`

请求：

```json
{ "config_version": 3 }
```

成功响应：`{ "data": { "status": "ok", "config_version": 3 } }`

回执成功后，服务端 `config_applied_version=3`，管理界面显示“终端已同步”。
若期间管理员又保存了新配置（version=4），心跳会再次返回 `config_pending=true`，
链路自动重跑，无需客户端特判。

### 4.5 运行数据上报 `POST /telemetry/v1/report`

请求：

```json
{
  "window_started_at": "2026-09-08T09:59:00Z",
  "token_usage_delta": 12500,
  "security_alerts_delta": 2,
  "alert_samples": [
    {
      "at": "2026-09-08T09:52:11Z",
      "stage": "tool_pre",
      "module": "tool_guard",
      "action": "block",
      "risk_score": 0.93,
      "reason": "intent_score=0.12; tool intent mismatch",
      "trace_id": "claw-8f3a..."
    },
    {
      "at": "2026-09-08T09:55:02Z",
      "stage": "output",
      "module": "io_guard",
      "action": "rewrite",
      "risk_score": 0.66,
      "reason": "matched output leakage pattern",
      "trace_id": "claw-8f3b..."
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
|------|------|------|
| `window_started_at` | 否 | 本窗口起点（上次成功上报时间），审计参考 |
| `token_usage_delta` | 否（默认 0） | **窗口内增量**：该终端上 LLM Token 消耗合计（prompt+completion）。统计口径建议：Argus 所在进程/Agent 产生的全部 LLM 调用，客户端在侧统计 |
| `security_alerts_delta` | 否（默认 0） | **窗口内增量**：安全预警次数。预警口径建议：Argus 判定动作 ≠ `allow` 的次数（block / rewrite / human_review） |
| `alert_samples` | 否 | 窗口内预警样本明细（上限 100 条），仅审计留存；服务端计数以 `security_alerts_delta` 为准 |

> **delta 的消费规则（重要，保证不重不漏）**：服务端只在处理成功（返回 200）
> 后累加计数；客户端**必须以收到 200 为标志清零本地窗口**，失败（网络错误/
> 5xx/429）则保留窗口数据并入下一轮重发。串行发送（同一时刻只有一个在途
> report 请求）。

成功响应：

```json
{
  "data": {
    "status": "ok",
    "token_usage_total": 125000,
    "alert_count_total": 18
  }
}
```

（`*_total` 为服务端聚合后的最新累计值，可用于客户端本地对账。）

上报周期建议：**60 秒**，可与心跳合并为一个定时任务（先 heartbeat，间隔后
report；两者独立接口，均可按各自节奏调用）。

### 4.6 Argus 配置包 v1（schema 定稿）

> 配置包 = 管理员在 LLMGate 控制台"修改配置"页面（可视化编辑器）保存后下发的
> **partial 增量包**：只包含被修改的键，其余含义 = "保持终端本地现状"。
> 字段默认值/说明的权威来源为 Argus 仓库 `CONFIGS.md`（2026-09 实测），
> 本节的字段速查与其一致，仅收录**已生效**配置项（声明但未接线的项不收）。

#### 4.6.1 包结构

```json
{
  "schema_version": 1,
  "modules": { "...": "模块启停/异常兜底与参数（对应本地 modules.yaml 的 modules.* 段；控制台按模块分组展示）" },
  "io_guard_policy": { "...": "IO Guard 检测策略（对应本地 default_policy.json）" },
  "access": { "...": "访问控制策略模型/风险联动/隔离（对应本地 ARGUS_* 环境变量）" },
  "access_rules": { "...": "规则文件原文（整体替换本地 resources.txt；users.txt 已下线，用户规则只保留在服务端）" },
  "retrieval": { "...": "Retrieval Guard 参数（白名单/注入/提示词包装）" },
  "integration": { "...": "OpenClaw 接入插件参数" }
}
```

#### 4.6.2 合并规则（客户端必须遵守）

| # | 规则 | 说明 |
|---|------|------|
| 1 | `schema_version` 校验 | 客户端只支持 `schema_version=1`；≠ 1 → **拒绝应用**、本地告警、不回执（服务端保持 pending 便于管理员排查） |
| 2 | 递归深合并 | 包内对象与本地目标逐键合并；包中未出现的键一律不改动 |
| 3 | 标量覆盖 | 包内标量（bool/number/string）直接覆盖本地值，含空串与 `0` |
| 4 | 数组整体替换 | 包内数组（工具名单/白名单等）**整体替换**本地数组，不做并集 |
| 5 | 空包/清空下发 | `config=""`（收回）→ 客户端不做任何变更，维持本地配置 |
| 6 | 未知键 | 包中出现本节未列出的键 → 忽略并记 warn 日志（为兼容未来字段，勿报错） |
| 7 | 敏感字段 | `modules.tool_guard.api_key` 若为 null/缺省 → 不覆盖本地密钥；值为非空串 → 覆盖（管理员确认下发） |

#### 4.6.3 字段速查（键路径 | 类型 | 默认 | 说明）

> 速查表按控制台可视化编辑器的**模块分组**给出（IO Guard 检测字段较多拆为两张表）；
> 键路径与默认值不变，分组仅是展示组织，不影响配置包解析。

**① IO Guard 检测 — 模块开关 `modules.io_guard_input/io_guard_context`（源：modules.yaml，CONFIGS.md §2.1）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `modules.io_guard_input.enabled` | bool | true | 输入检测启停 |
| `modules.io_guard_input.on_error` | enum | allow | 模块异常兜底 allow/block/ignore |
| `modules.io_guard_input.media_extraction` | bool | true | 附件先抽取文本再检测 |
| `modules.io_guard_context.enabled` | bool | true | 上下文复检启停 |
| `modules.io_guard_context.on_error` | enum | allow | 同上 |

**② IO Guard 检测 — 检测策略 `io_guard_policy`（源：default_policy.json，CONFIGS.md §3；`audit.*` 两键见 ⑥ 审计）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `io_guard_policy.decision_thresholds.rewrite` | number | 0.55 | 低于 → allow |
| `io_guard_policy.decision_thresholds.block` | number | 0.85 | 高于 → block |
| `io_guard_policy.question_decomposition.enabled` | bool | true | 长问题分解（拆子查询分别送检） |
| `io_guard_policy.question_decomposition.min_chars` | int | 60 | 触发分解最小长度 |
| `io_guard_policy.question_decomposition.max_parts` | int | 8 | 最大拆分数量 |
| `io_guard_policy.question_decomposition.strategy` | string | lossless_heuristic_v1 | 分解策略名 |
| `io_guard_policy.semantic_detection.enabled` | bool | true | 语义模型检测开关 |
| `io_guard_policy.semantic_detection.backend` | string | stage_char_classifier | 检测后端 |
| `io_guard_policy.semantic_detection.model_dir` | string | "" | 相对 policy 目录；空 = 不动 |
| `io_guard_policy.semantic_detection.policy_score` | number | 0.9 | 语义证据计入总分权重 |
| `io_guard_policy.semantic_detection.detector_threshold` | number | 0.55 | 通用命中阈值 |
| `io_guard_policy.semantic_detection.threshold_overrides.input` | number | 0.6825 | 阶段阈值覆盖 |
| `io_guard_policy.semantic_detection.threshold_overrides.output` | number | 0.3 | 同上 |
| `io_guard_policy.semantic_detection.threshold_overrides.content` | number | 0.7 | 同上 |
| `io_guard_policy.media_extraction.enabled` | bool | true | 附件抽取总开关 |
| `io_guard_policy.media_extraction.max_file_bytes` | int | 15728640 | 单附件上限（字节，15MB） |
| `io_guard_policy.media_extraction.max_text_chars` | int | 50000 | 抽取文本送检上限 |
| `io_guard_policy.media_extraction.max_attachments` | int | 5 | 单请求附件数上限 |
| `io_guard_policy.media_extraction.remote.max_bytes` | int | 5242880 | 远程附件上限（字节，5MB） |
| `io_guard_policy.media_extraction.remote.timeout_ms` | int | 8000 | 远程下载超时 |
| `io_guard_policy.media_extraction.ocr.enabled` | bool | true | OCR 开关 |
| `io_guard_policy.media_extraction.ocr.lang` | string | ch | OCR 语言 |
| `io_guard_policy.media_extraction.ocr.device` | enum | cpu | cpu/cuda |
| `io_guard_policy.media_extraction.ocr.max_images` | int | 4 | 单请求 OCR 图片上限 |

**③ Tool Guard `modules.tool_guard`（源：modules.yaml + TOOL_GUARD_*，CONFIGS.md §2.1/§6）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `modules.tool_guard.enabled` | bool | true | Tool Guard 启停 |
| `modules.tool_guard.on_error` | enum | block | LLM 异常兜底 |
| `modules.tool_guard.base_url` | string | https://api.deepseek.com/v1 | OpenAI 兼容端点 |
| `modules.tool_guard.api_key` | string | "" | 密钥；空/缺省 = 不覆盖本地 |
| `modules.tool_guard.model` | string | deepseek-chat | 模型名 |
| `modules.tool_guard.timeout_seconds` | int | 30 | 调用超时（秒） |
| `modules.tool_guard.block_threshold` | number | 0.4 | 匹配分 < 此值 → block |
| `modules.tool_guard.review_threshold` | number | 0.7 | 0.4~0.7 → human_review |
| `modules.tool_guard.fetch_guard.enabled` | bool | true | 抓取前置判定开关 |
| `modules.tool_guard.fetch_guard.shell_tools` | string[] | [execute_bash,exec,bash,shell,sh,terminal,cmd,powershell] | curl/wget 扫描工具名单 |
| `modules.tool_guard.fetch_guard.url_tools` | string[] | [browser] | URL 导航工具名单 |

**④ Retrieval Guard（源：modules.yaml §2.1 + whitelist.yaml / b_injection/config.yaml / c_prompt/config.yaml §5）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `modules.retrieval_guard.enabled` | bool | true | Retrieval Guard 总开关 |
| `modules.retrieval_guard.on_error` | enum | allow | 同上 |
| `modules.retrieval_guard.model_path` | string | "" | PIGuard 模型目录（相对项目根）；空 = 不动 |
| `modules.retrieval_guard.guards.A` | bool | true | A 层 URL 白名单 |
| `modules.retrieval_guard.guards.B` | bool | true | B 层 PIGuard 注入检测 |
| `modules.retrieval_guard.guards.C` | bool | true | C 层提示词包装 |
| `retrieval.whitelist.trusted` | string[] | [] | 整体替换白名单（fnmatch 通配）；空数组 = 不覆盖 |
| `retrieval.whitelist.blocked` | string[] | [] | 整体替换黑名单；空数组 = 不覆盖 |
| `retrieval.injection.threshold` | number | 0.95 | 注入概率拦截阈值 |
| `retrieval.injection.window_size` | int | 400 | 滑窗大小（token ≤512） |
| `retrieval.injection.step` | int | 200 | 滑窗步长 |
| `retrieval.prompt_wrap.random_length` | int | 10 | Spotlighting 随机序列长度 |
| `retrieval.prompt_wrap.self_reminder` | string | "" | 行为契约文案（空 = 不覆盖） |
| `retrieval.prompt_wrap.post_prompting` | string | "" | 后置指令文案（空 = 不覆盖） |

**⑤ 访问控制（源：modules.yaml §2.1 + ARGUS_* env §4.2/4.3 + 规则文件 §4.1）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `modules.access_control.enabled` | bool | true | 访问控制启停 |
| `modules.access_control.on_error` | enum | block | 同上 |
| `access.mode` | enum | rbac | rbac/mac/hybrid |
| `access.block_unknown_users` | bool | false | 未知用户直接拦截 |
| `access.risk_link_enabled` | bool | true | 审计风险联动开关（关 = 纯 RBAC） |
| `access.risk_window_seconds` | int | 300 | 风险滑窗（秒） |
| `access.risk_threshold` | number | 0.6 | 单事件高风险阈值 |
| `access.risk_probe_block_count` | int | 3 | 试探标记拦截数 |
| `access.risk_escalation_threshold` | number | 0.5 | 防线升级阈值 |
| `access.quarantine_enabled` | bool | true | 隔离总开关 |
| `access.quarantine_block_count` | int | 8 | 5 分钟窗内拦截数触发隔离 |
| `access.quarantine_risk_threshold` | number | 0.85 | probe 且风险 ≥ 此值隔离 |
| `access.quarantine_long_window_seconds` | int | 3600 | 长窗时长 |
| `access.quarantine_long_window_count` | int | 15 | 长窗触发拦截数 |
| `access_rules.users` | string | "" | 已下线：终端收到后忽略并记 warn，用户规则只保留在服务端 |
| `access_rules.resources` | string | "" | 整体替换本地 resources.txt；行格式 `路径模式 | 等级 | flat/inherit/override` |

**⑥ 审计（源：modules.yaml §2.1 + default_policy.json 的 audit 段 §3）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `modules.audit.enabled` | bool | true | 审计启停 |
| `modules.audit.on_error` | enum | ignore | 审计异常不阻断业务 |
| `io_guard_policy.audit.content_storage` | string | sanitized | 审计正文存储策略 |
| `io_guard_policy.audit.max_content_chars` | int | 2000 | 审计正文截断上限 |

**⑦ 沙箱 `modules.sandbox`（源：modules.yaml sandbox 段）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `modules.sandbox.enabled` | bool | true | 沙箱接入开关 |
| `modules.sandbox.mode` | enum | mcp | 接入方式 |
| `modules.sandbox.url` | string | http://127.0.0.1:9876 | Sandbox MCP 地址 |

**⑧ 人工复核 `modules.human_review`（源：modules.yaml human_review 段）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `modules.human_review.unsupported_action` | enum | block | 不支持动作兜底（block/allow） |

**⑨ OpenClaw 集成 `integration`（源：openclaw 插件配置，CONFIGS.md §9）**

| 键 | 类型 | 默认 | 说明 |
|----|------|------|------|
| `integration.argus_url` | string | http://127.0.0.1:8000 | Argus API 地址 |
| `integration.api_token_env` | string | ARGUS_API_TOKEN | 令牌环境变量名 |
| `integration.timeout_ms` | int | 30000 | HTTP 调用超时 |
| `integration.fail_mode` | enum | closed | closed/open |
| `integration.enable_media_check` | bool | true | 附件送检 |
| `integration.media_root` | string | "" | 附件根目录（空 = 协议默认） |
| `integration.protected_tools` | string[] | [web_fetch,web_search] | 回检保护工具名单 |

#### 4.6.4 客户端本地映射职责

配置包键是**集控语义**的收敛命名，客户端负责映射到本地各载体后再合并：

| 包键前缀 | 建议映射目标（客户端工程定稿） |
|----------|------------------------------|
| `modules.*` | 本地 `configs/modules.yaml` 的 `modules.*` 段 |
| `io_guard_policy.*` | 本地 IO Guard `default_policy.json`（顶层键一一对应） |
| `access.*` | 本地 `auth_gateway.py` 读取的 `ARGUS_*`/`TOOL_GUARD_*` 环境变量（或等价持久配置源） |
| `access_rules.*` | 本地 `resources.txt`（整体替换；users 键已下线，终端忽略） |
| `retrieval.*` | 本地 `whitelist.yaml` / `b_injection/config.yaml` / `c_prompt/config.yaml` |
| `integration.*` | OpenClaw 插件配置段 `plugins.entries."argus-adapter".config.*` |
| `modules.tool_guard.base_url/api_key/model/...` | 本地 tool_guard 配置段及 `TOOL_GUARD_LLM_*` 环境变量（注意本地 env 优先级高于 yaml，客户端需按自身优先级写入生效层） |

#### 4.6.5 设计边界（为什么没有某些配置）

- 仅收录 Argus `CONFIGS.md` 中**已生效**的配置；标注 ⚠️ 的"声明未接线"项
  （如 policy.yaml `stages` 拓扑、`sandbox_config.yaml` 资源、`TOOL_GUARD_AUDIT_API_URL`）
  不属于配置包，避免误导客户端实现。
- 存储路径类（`ARGUS_AUDIT_PATH` 等）属于终端本地部署参数，集控不下发。
- 包内不含密钥明文策略：`api_key` 由管理员显式填写才会下发；令牌类仍走环境变量。

### 4.7 审计事件批量上传 `POST /telemetry/v1/audit/events`

> 终端把本地 Argus 审计层产生的 `AuditEvent` 全量（含 `allow`）周期上报，
> 集控端入库后在控制台"审计日志 → 终端审计"板块浏览/筛选/导出。
> 服务端已实现（表 `agent_audit_events`）；本节为客户端上传器契约。

请求：`events` 数组内每条对应本地审计 JSONL 的一条 AuditEvent（字段名一致）：

```json
{
  "events": [
    {
      "event_id": "module-audit-…uuid5…",
      "trace_id": "claw-…",
      "session_id": "sess-1",
      "user_id": "zhangsan",
      "timestamp": "2026-09-08T09:52:11Z",
      "stage": "tool_pre",
      "source_module": "tool_guard",
      "action": "block",
      "risk_score": 0.93,
      "reason": "intent_score=0.12; tool intent mismatch",
      "content": { "tool": "execute_bash", "summary": "正文已按本地 audit.content_storage 策略脱敏/截断" },
      "metadata": { "argus_version": "2.1.0" }
    }
  ]
}
```

字段规则：

| 字段 | 必填 | 约束 |
|------|------|------|
| `event_id` | 是 | ≤128 字符，终端内唯一（建议直接用本地审计事件幂等键 uuid5）。服务端以 (terminal_id, event_id) 判重：重复上报已存在事件 → 忽略并计入响应 `duplicates`，不会产生重复行 |
| `timestamp` | 是 | ISO 8601（推荐 UTC）；服务端归一化为 UTC 秒级定宽存储（文本序 = 时间序，支持区间筛选） |
| `stage`/`source_module`/`action` | 是 | ≤32/≤64/≤32 字符；`action` 仅允许 `allow`/`block`/`rewrite`/`human_review`（其他值 → 400） |
| `risk_score` | 否（默认 0） | ∈ [0, 1] |
| `reason` | 否 | ≤4096 字节 |
| `content`/`metadata` | 否 | JSON 对象（缺省 `{}`）；序列化后单对象 ≤ 64KB |
| `trace_id`/`session_id`/`user_id` | 否 | ≤128/≤128/≤64 字符；`user_id` 为 Argus 侧用户标识字符串（非 LLMGate 用户 ID） |

批次规则：

- 单批 ≤ **500** 条；按 `event_time` 升序分批发送。
- **整批全有或全无**：任一条非法 → 整批 `400`（message 带 `events[i]` 索引定位），
  不产生部分入库；客户端应修复后整批重发，防止缺陷静默丢事件。

成功响应：

```json
{ "data": { "status": "ok", "accepted": 3, "duplicates": 1 } }
```

`accepted` = 本批新增条数；`duplicates` = 批内重复 + 服务端已存在合计。

客户端职责：

- **权威副本在本地**：本地审计 JSONL 只追加、永不清除；集控仅作汇聚展示，其
  保留策略由集控管理员配置（与"行为审计"同一保留期参数，默认 90 天），客户端
  不可依赖集控长期留存明细。
- 周期上传建议 **60 秒**（可与 report 同一定时任务），窗口 = 上次成功上传游标之后的全部事件；
  串行发送（同一时刻只有一个在途请求）。
- **以收到 200 为准推进游标**；网络错误/5xx/429/4xx → 不推进，下轮重试
  （4xx 需先按 message 修复；幂等保证重发无害）。

---

## 5. 数据口径约定（管理表格列 ← 上报字段映射）

| 控制台表格列 | 数据来源 |
|--------------|----------|
| 终端名称 / 描述 / Agent 类型 | 管理员创建/编辑时录入 |
| 绑定用户 | 管理员创建/编辑时绑定 LLMGate 用户（决定 LLM key 归属） |
| LLM 密钥 | 注册时平台自动签发（密钥管理列表中“来源=终端下发”，所有者在终端改绑时同步） |
| 终端计算机名 | 注册 + 心跳 `hostname`（心跳幂等更新） |
| Argus 版本 / Agent 版本 | 注册 + 心跳上报 |
| 状态（在线/离线/未注册） | 在线 = 已注册且最近心跳 ≤ 120 秒；离线 = 已注册但心跳超时；未注册 = 仅创建/被吊销 |
| Token 消耗数 | `report.token_usage_delta` 服务端累加（`token_usage_total`） |
| 安全预警次数 | `report.security_alerts_delta` 服务端累加（`alert_count_total`） |
| 配置下发/应用状态 | 管理员保存（version+1）与客户端回执（applied version）对照 |
| 审计日志 · 终端审计（时间/终端/阶段/模块/动作/风险/理由/内容/元数据） | `audit/events` 上报的 AuditEvent（§4.7；终端名为上报时刻快照，终端删除后历史仍保留） |

---

## 6. 客户端本地配置建议结构

客户端需新增一段遥测配置（示意，最终由客户端工程定稿）：

```jsonc
// config/remote.json
{
  "remote": {
    "base_url": "http://gate.example.com:8080",
    "registration_code": "<管理员下发的一次性注册码>",
    "token": "<注册成功后持久化>",
    "terminal_id": 1,
    "heartbeat_interval_seconds": 60,
    "report_interval_seconds": 60
  },
  "llm": {
    "api_key": "<注册响应 llm.api_key，持久化>",
    "base_url": "<注册响应 llm.base_url，即平台 OpenAI 兼容端点>",
    "enterprise_name": "<注册响应 llm.enterprise_name，供展示>"
  }
}
```

运行流程建议：启动 → 若无 token 或上次注册失败 → 用 registration_code 注册 →
成功后持久化 `remote.token` 与 `llm.*` → 进入周期循环（心跳/上报/配置拉取），
Agent 的 LLM 配置指向 `llm.base_url` + `llm.api_key`。参见 §8 异常矩阵。

---

## 7. 管理端接口（控制台，客户端工程师联调时使用）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/admin/terminals?agent_type=&keyword=&page=&page_size=` | 终端列表（含在线状态/聚合指标/LLM 密钥 #id） |
| POST | `/api/admin/terminals` | 添加终端（返回一次性注册码；注册成功时平台自动签发 LLM key） |
| PUT/DELETE | `/api/admin/terminals/:id` | 编辑/删除终端（改绑用户时同步 LLM key 归属；删除先停用其 key） |
| POST | `/api/admin/terminals/:id/regenerate-code` | 重新生成注册码（旧码失效） |
| POST | `/api/admin/terminals/:id/revoke` | 吊销令牌/注册码并停用其 LLM key（终端需重生成码后重注册，届时签发新 key） |
| GET/PUT | `/api/admin/terminals/:id/config` | 查看/保存下发配置 |
| GET | `/api/admin/api-keys` | 密钥列表（含所属用户/来源终端/权限白名单） |
| POST | `/api/admin/api-keys` | 手动添加密钥：name + 可选绑定 user_id + 权限白名单（留空=全部模型）；明文仅返回一次 |
| PUT | `/api/admin/api-keys/:id` | 编辑密钥：名称 + 权限模型白名单（留空=全部模型；全量更新两字段） |
| POST | `/api/admin/api-keys/:id/deactivate` | 停用密钥（保留在列表中；终端引用同步解除） |
| DELETE | `/api/admin/api-keys/:id` | 物理删除密钥（不可恢复；先解除终端关联，终端需重新注册获取新 key） |
| GET/PUT | `/api/admin/settings` | 系统设置：企业名称/系统根地址/开放模型（驱动注册下发的 base_url 与 key 权限） |
| GET | `/api/admin/models` | 全部可用模型（供系统设置“开放模型”勾选） |
| PUT | `/api/admin/change-password` | 当前登录管理员改密（含首次登录强制改密） |
| GET | `/api/admin/audit-events?terminal_id=&stage=&action=&source_module=&risk_min=&q=&start_time=&end_time=&page=&page_size=` | 终端审计事件列表（§4.7 上报数据；`q` 模糊匹配终端/链路/用户/事件ID/理由） |
| GET | `/api/admin/audit-events/stats` | 终端审计汇总（累计/今日事件/今日非放行/今日高危≥0.7） |
| GET | `/api/admin/audit-events/terminal-stats` | 各终端审计聚合（“审计日志 · 终端审计”左栏列表；无审计终端也返回，按最近审计时间倒序） |
| GET | `/api/admin/audit-events/export` | 导出终端审计 CSV（含当前筛选条件） |
| GET | `/api/admin/extensions/approvals?state=&kind=&terminal_id=&keyword=&page=&page_size=` | 安装审批单列表（skill/MCP） |
| GET | `/api/admin/extensions/approvals/stats` | 审批汇总（待审批 / 今日新增 / 通过 / 驳回） |
| POST | `/api/admin/extensions/approvals/:id/approve` · `reject` | 人工审批（驳回必须填理由 note，仅 pending 可流转） |
| GET/POST | `/api/admin/extensions/skill-packages` | Skill 包列表 / 上传（multipart zip；同名上传 = 更新，version+1） |
| PUT/DELETE | `/api/admin/extensions/skill-packages/:id` | 编辑描述 / 删除包（连带解除对全部分发终端） |
| GET/PUT | `/api/admin/extensions/skill-packages/:id/assignments` | 查看 / 全量覆盖某包的分发终端集合 |
| GET | `/api/admin/extensions/terminal-options` | 全部终端轻量列表（分发多选用） |
| GET/PUT | `/api/admin/extensions/default-skill-packages` | 新终端默认自动分发包（`{enabled, package_ids}`，注册时生效） |

> 控制台登录仅允许 **admin** 角色（`POST /api/auth/login` 对非 admin 返回 403
> `admin_only`）。原 `/api/user/*` 自助接口（个人密钥/用量/改密）已随“普通用户
> 界面移除”一并下线；普通用户账号仍可创建，作为终端绑定与配额归属对象。

---

## 8. 异常处理矩阵

| 场景 | 现象 | 客户端行为 |
|------|------|-----------|
| 注册码错误/过期 | 401 `invalid_registration_code` | 本地告警，等待管理员重新下发注册码 |
| agent_type 不匹配 | 409 | 检查本地 agent_type 声明与登记是否一致 |
| 令牌失效/被吊销 | 401 `invalid_telemetry_token` | 停止心跳；有注册码则重新注册换新令牌；仍失败则本地告警降级离线 |
| LLM key 失效/被停用 | LLM 请求 401 `invalid_api_key` | 检查 key 是否被吊销/停用；若终端被吊销，等管理员重新生成注册码后重注册换取新 key |
| LLM 模型越权 | LLM 请求 403 `model_not_permitted` | 请求改用系统设置“开放模型”内的模型，或联系管理员调整 |
| 网络不可达 | 超时/连接失败 | 指数退避重试（1s→2s→…封顶 60s），恢复后立即补一次心跳与滞留的 report 窗口 |
| 上报失败(5xx/429) | 错误响应 | **保留窗口数据**，下轮合并重发（见 §4.5） |
| 审计上传 400 | `invalid_event`/`batch_too_large`，message 含 `events[i]` 索引 | 整批未落库：修复该事件后整批重发（§4.7）；**不推进**上传游标 |
| 审计上传失败(网络/5xx/429) | 无 200 | **保留本地窗口与游标**，退避重试；收到 200 才推进（§4.7，重复重发幂等无害） |
| 配置应用失败 | 无回执 | 不调用 applied；本地告警；按 5 分钟周期重试拉取并应用 |
| 配置包 schema_version 不匹配 | 拉取到未知版本配置包 | **拒绝应用**、本地告警、不回执（服务端保持 pending，提示客户端升级或管理员介入） |
| 心跳 200 但 config_pending | 响应字段 | 立即 GET /config → 应用 → POST applied |
| 审批申请被驳回 | 审批单 state=rejected | **不得安装/接入**；将 `review_note` 展示给使用者，可修改后重新发起新申请 |
| 审批结果拉取为空 | 轮询 200 无新单 | 按节奏继续轮询（提交后建议 30s/次） |
| 心跳/注册 skills_pending=true | 响应字段 | 执行 CLIENT.md §3：GET /skills → 安装 → 回执 |
| 拉取到的新包安装失败 | 回执 ok=false | 记录失败原因，按节奏重试安装并再次回执（服务端保持待同步） |
| 对未分配的包回执 | 400 “该 skill 包未分配给本终端” | 停止该包尝试；只对拉取到的包做回执 |

---

## 9. 本地联调指引（curl）

```bash
# 1) 管理员先通过控制台添加终端，拿到 registration_code；或直接调用：
curl -s -X POST http://127.0.0.1:8080/api/admin/terminals \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"dev-test","agent_type":"openclaw"}' | jq

# 2) 模拟客户端注册（用上一步返回的 registration_code）
#    响应 data 含 token 与 llm{api_key,base_url,enterprise_name}（均仅一次）
curl -s -X POST http://127.0.0.1:8080/telemetry/v1/register \
  -H "Content-Type: application/json" \
  -d '{"registration_code":"<code>","hostname":"dev-mac","agent_version":"2026.6.11","argus_version":"2.1.0","agent_type":"openclaw"}'

# 2.1) 用注册下发的 LLM 凭据查询可用模型（base_url 已含 /v1；可按需设置先行：
#      curl -s -X PUT http://127.0.0.1:8080/api/admin/settings -H "Authorization: Bearer <admin-jwt>" ...）
curl -s http://127.0.0.1:8080/v1/models -H "Authorization: Bearer <llm.api_key>"

# 3) 心跳（TOKEN 为注册响应中的 token）
curl -s -X POST http://127.0.0.1:8080/telemetry/v1/heartbeat \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"hostname":"dev-mac","argus_version":"2.1.0"}'

# 4) 管理员在控制台"修改配置"保存 JSON 后，客户端拉取：
curl -s http://127.0.0.1:8080/telemetry/v1/config \
  -H "Authorization: Bearer <TOKEN>"

# 5) 上报
curl -s -X POST http://127.0.0.1:8080/telemetry/v1/report \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"token_usage_delta":1200,"security_alerts_delta":1,"alert_samples":[{"at":"2026-09-08T10:00:00Z","stage":"input","module":"io_guard","action":"block","risk_score":0.9,"reason":"prompt injection","trace_id":"t1"}]}'

# 6) 批量上传审计事件（同一 (终端, event_id) 重复上传会幂等忽略；见 §4.7）
curl -s -X POST http://127.0.0.1:8080/telemetry/v1/audit/events \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"events":[{"event_id":"e2e-001","trace_id":"t1","session_id":"s1","user_id":"dev","timestamp":"2026-09-08T10:00:00Z","stage":"tool_pre","source_module":"tool_guard","action":"block","risk_score":0.93,"reason":"demo block","content":{"tool":"execute_bash"},"metadata":{"k":"v"}}]}'
```

---

## 10. 扩展治理速查（skill/MCP 审批 + Skill 分发）

> 客户端完整对接规范见 [CLIENT.md](./CLIENT.md)；Skill 压缩包制作规范见
> [SKILL_CREATION.md](./SKILL_CREATION.md)。本节只列端点到主协议的映射速览。

| 场景 | 端点（均 Bearer 鉴权） | 说明 |
|------|------|------|
| 安装前上报审批申请 | `POST /telemetry/v1/extensions/requests` | kind=skill\|mcp；响应含 request_id 与 state |
| 轮询审批结果 | `GET /telemetry/v1/extensions/requests` | 返回本终端最近审批单，按 (id, state) 对账 |
| 拉取已分配的 skill 包 | `GET /telemetry/v1/skills` | zip base64 + version；附回执状态与 pending_count |
| 安装结果回执 | `POST /telemetry/v1/skills/applied` | package_id + version + ok/message |
| 心跳/注册带待办标记 | 响应字段 `skills_pending` | 见 §4.1 / §4.2 |

状态机速记：

- 审批：`pending → approved | rejected`（驳回必带理由；自动审批接口已预留，
  当前默认人工审批）。
- Skill 同步口径：某包“已同步” = 最近回执 `status=ok` 且回执版本 ≥ 包当前版本；
  否则服务端在心跳/注册响应中标 `skills_pending=true`。

---

## 11. 扩展性说明（服务端已预留）

- **Agent 类型扩展**：`agent_type` 为自由字符串，管理端当前展示白名单
  `openclaw`；新增类型（如 `claude_code`）只需在服务端类型表追加，协议无需变化。
- **配置包版本演进**：配置包顶层 `schema_version` 独立于 `config_version`（后者是
  服务端每次保存的单调递增号）。新增字段只需把 `schema_version` 升到 2 并保留
  v1 兼容读取（未知键忽略规则已保证向后兼容）；客户端实现对未知版本应拒应用。
- **审计事件明细落库**：终端 Argus 审计事件经 `POST /telemetry/v1/audit/events`
  全量汇聚到 `agent_audit_events` 表（幂等去重，见 §4.7），控制台"审计日志 →
  终端审计"浏览/筛选/导出，并按保留期自动清理。`report.alert_samples` 仍是窗口
  摘要日志，与明细两套语义并存、互不计数。
- **扩展治理（已实现）**：skill/MCP 安装审批（默认人工；`service.ApprovalDecider`
  策略接口 + 系统设置 `extension_approval_mode=auto` 已预留自动审批）与 Skill 包
  分发（目标终端分配 + 新终端默认包自动分配）均已上线，见 §10；终端侧对接见
  [CLIENT.md](./CLIENT.md)，压缩包制作规范见 [SKILL_CREATION.md](./SKILL_CREATION.md)。
- **聚合指标维度**：若未来需要按日/周趋势，客户端可另报时间分桶数据
  （新增字段即可），当前累计值字段不受影响。
