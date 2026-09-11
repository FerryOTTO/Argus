# OpenClaw Clawguard Adapter

该插件负责在 OpenClaw 与统一 Clawguard FastAPI 之间转换请求和执行动作，不再
直接调用 IO Guard Sidecar。风险判断仍以 Clawguard 为准；插件仅保留一组与后端占位符
一致的确定性脱敏规则，用于无法异步请求 HTTP 的会话持久化 Hook。

## 统一接口

| OpenClaw Hook | Clawguard 接口 | 行为 |
|---|---|---|
| `before_agent_run` | `POST /v1/input/check`，随后 `POST /v1/tool/session/prompt` | 输入允许或合法改写后，用本轮原始 prompt 绑定 Tool Guard 会话 |
| `before_tool_call` | `POST /v1/tool/pre_check` | 执行前应用 `allow/block/human_review/rewrite`；人工复核使用 OpenClaw 原生 `requireApproval` |
| `agentToolResultMiddleware` | `POST /v1/content/check` | 等待检查完成并在工具结果进入模型前放行、改写或隔离 |
| `after_tool_call` | `POST /v1/tool/session/call`，必要时 `POST /v1/content/check` | 先回写真实已执行工具；之后仅对受保护工具执行兼容内容检查 |
| `tool_result_persist` | 不发 HTTP | 同步应用缓存的 `allow/rewrite/block` 结果 |
| `before_message_write` | 本地同步脱敏 | 持久化前递归遮蔽助手回复、工具参数和工具结果中的敏感数据 |
| `message_sending` | `POST /v1/output/check` | 原样发送、发送安全的 `data.text` 或替换为阻断提示 |
| `reply_payload_sending` | `POST /v1/output/check` | 覆盖 WebChat/Control UI 等回复载荷，确保网页端同样显示占位符 |

`after_tool_call` 是异步旁路 Hook，而 `tool_result_persist` 是同步 Hook，二者无法安全
完成“先 HTTP 检查、再进入模型”的时序。插件使用 OpenClaw 2026.6.11 兼容的
`agentToolResultMiddleware`：它会等待 `/v1/content/check` 返回，并在结果进入模型上下文
前直接应用 `allow/rewrite/block`。四个原 Hook 仍保留；`reply_payload_sending`
补齐网页聊天回复的输出检查，`before_message_write` 保证网页历史和会话文件不保存
助手/工具回显中的原始敏感值，`after_tool_call` 作为兼容路径，
`tool_result_persist` 保证工具结果一致。若缓存因重启等原因缺失，`closed` 会隔离结果，
只有显式配置 `open` 才保留原结果。

`before_tool_call` 会按真实 `tool_call_id` 暂存本次调用的 `trace_id`、`session_id`、
身份上下文和该 Trace 内从 0 递增的工具调用 `sequence`。工具结果中间件即使拿不到
OpenClaw 的 run/session 字段，也会通过
同一个 `tool_call_id` 复用原链路信息，避免一次 Agent 任务的工具前检查与内容检查
被拆成多个 Trace；缓存带有短期 TTL，并在工具完成或 Gateway 停止时清理。

IO Guard 输出只返回 `allow`、`rewrite` 或 `block`。`rewrite` 时插件仅投递后端返回的
`data.text` 净化文本；`block` 时不投递原始输出。工具调用阶段仍可由 Tool Guard 使用
OpenClaw 原生 `requireApproval`，该行为不属于 IO Guard。
用户原始输入不在 `before_message_write` 中改写，以保留输入审计语义。

OpenClaw 原生 `before_agent_run` 契约只接受 `pass/block`，不消费 Hook 对事件中
`prompt` 的修改。插件收到 Clawguard `rewrite` 时把 `event.prompt` 改成 `data.text` 并
返回标准 `{ outcome: "pass" }`；兼容补丁会在模型调用前消费这个净化后的输入，同时
保留原始用户消息以便审计。

兼容补丁和应用说明位于
`openclaw_adapter/patch_source/clawguard-adapter/README.md`。未应用补丁时，插件会
返回标准 `pass`，但当前 OpenClaw 不会消费事件修改，因此输入改写不会生效。

工具名只在本 Adapter 边界做以下兼容转换，原名同时以 `original_tool_name` 送入
`/v1/tool/pre_check`：

```text
read → read_file       write/edit → write_file
exec → execute_bash    web_fetch → http_request
web_search → web_search
```

未知工具保持原名。`apply_patch` 可能涉及多条文件路径，本阶段不声明完整资源解析能力。
`block` 不执行工具，因此不会产生 `/session/call`；`human_review` 不自动放行，审批超时
按拒绝处理；`rewrite` 仅在响应明确包含对象类型的 `data.arguments` 时应用。

受控演示环境可将特定工具加入插件配置 `humanReviewAutoAllowTools`。此时上游安全模块
仍会真实返回并审计 `human_review`，但 Adapter 会记录警告后继续执行白名单中的工具。
默认列表为空；生产环境不得配置该演示白名单。

`web_search` 结果会先提取结构化的 `title`、`description`、`excerpt`、`content`
和 URL，并移除 OpenClaw 自己添加的 `EXTERNAL_UNTRUSTED_CONTENT` 边界标记，再交
给 Clawguard 检测。边界标记不会再作为自然文本触发误报，但标记内部的真实提示
注入指令仍会被保留并检测。

所有请求都使用统一结构：

```json
{
  "context": {
    "trace_id": "trace-001",
    "session_id": "session-001",
    "user_id": "user-001",
    "stage": "input",
    "timestamp": "2026-08-05T08:00:00.000Z"
  },
  "payload": {
    "text": "用户输入"
  }
}
```

## 环境与构建

- OpenClaw：插件 SDK、最低 Gateway 版本和兼容补丁统一为 `2026.6.11`
- Node.js：使用 OpenClaw 支持的版本
- Clawguard：默认 `http://127.0.0.1:8000`

```powershell
npm.cmd install
npm.cmd run check
npm.cmd run build
```

单元测试覆盖统一接口契约、所有 Hook 注册、工具结果进入模型前的检查与动作应用、
输入改写、缓存缺失策略，以及 `web_search` 结构化内容提取：

```powershell
npm.cmd test
```

## 最小配置

```json5
{
  plugins: {
    entries: {
      "clawguard-adapter": {
        enabled: true,
        hooks: {
          allowConversationAccess: true,
          timeoutMs: 31000,
          timeouts: {
            before_agent_run: 31000,
            after_tool_call: 31000,
            message_sending: 31000
          }
        },
        config: {
          clawguardUrl: "http://127.0.0.1:8000",
          apiTokenEnv: "CLAWGUARD_API_TOKEN",
          timeoutMs: 30000,
          failMode: "closed",
          enableMediaCheck: true,
          mediaRoot: "C:\\Users\\<you>\\.openclaw\\media",
          protectedTools: [
            "web_fetch", "web_search", "read", "write", "edit",
            "memory_search", "memory_get"
          ]
        }
      }
    }
  }
}
```

默认 HTTP 超时为 30 秒，以容纳 CPU OCR；可按服务实测 p99 在 `250–60000ms` 内配置，
OpenClaw Hook 超时必须比它至少多 500ms。`enableMediaCheck` 控制是否把消息附件送入
输入检查，`mediaRoot` 指向 OpenClaw 媒体根目录；留空时使用
`~/.openclaw/media`。插件只解析 `media://inbound/<id>` 到该目录内部，阻止路径越界。
服务启动后建议先访问 `/health` 并执行一次预热请求再接收流量。身份信息缺失时按外部
用户、公开渠道和空数据权限处理。生产环境建议保持 `failMode=closed`。如统一 FastAPI
尚未实现 Bearer Token，可将 `CLAWGUARD_API_TOKEN` 留空。

Tool Guard 会话数据的 TTL、跨轮次保留、工具链上限、模型、风险阈值和接口超时均由
现有模块或既有 Adapter 配置负责，本插件不会清理会话或调整这些值。真实实验应为每组
任务使用全新的 `session_id`。缺少真实 `senderId` 时使用现有 `default_user` fallback，
工具检查请求会标记 `identity_correlation_quality=fallback`，不能据此声称完成了真实
多用户权限验证。
