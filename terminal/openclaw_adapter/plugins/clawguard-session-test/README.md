# Clawguard Session Test（审计数据源插件）

OpenClaw 侧全流程审计数据源：把输入 / 工具调用 / 输出事件上报 Clawguard `/v1/audit/event`。

## 1. 职责

```
用户发消息      → message_received hook      → POST /v1/audit/event（stage=input）
AI 调 web 工具  → before_tool_call hook      → POST /v1/audit/event（stage=tool）
AI 回复发出     → reply_payload_sending hook → POST /v1/audit/event（stage=output）
```

**观察者**：fire-and-forget 上报（`void`），失败静默，绝不影响 OpenClaw 主流程。

## 2. 会话字段映射

| OpenClaw 字段 | 上报字段 | 说明 |
|---|---|---|
| `ctx.sessionKey` | `session_id` | 会话标识（`agent:main:dashboard:<uuid>`） |
| `ctx.runId` | `trace_id` | 轮次链路；input 阶段 ctx 无 runId，用 `messageId` 兜底（二者同值） |
| `event.toolCallId` / `ctx.messageId` | `content` | 阶段细节 |
| `ctx.sessionId` | `content.session_id_detail` | 工具阶段才有的补充 |
| `ctx.trace` | `content.trace` | OpenTelemetry 追踪信息（工具阶段） |

## 3. 安装

```powershell
cd ClawguardV2.1
openclaw plugins install .\openclaw_adapter\plugins\clawguard-session-test --force
openclaw gateway stop
schtasks /End /TN "OpenClaw Gateway"   # 如安装过计划任务
openclaw gateway run
```

启动日志确认插件列表包含 `clawguard-session-test`。

## 4. 验证

触发一轮对话（如 web_fetch + 总结），Clawguard 窗口应出现多条 `POST /v1/audit/event 200 OK`；
落盘文件 `runtime/audit/<日期>.jsonl` 中出现同一 `trace_id` 的 input/tool/output 事件链。

## 5. 说明

- 命名仍是 `clawguard-session-test`（观测期名称）；正式化时可改名为 `clawguard-audit`
- 上报目标地址 `CLAWGUARD_URL` 在 `dist/index.js` 顶部，可改
- 将来审计模块需要扩展事件类型（如 exec 调用、审批决策）时，在 `register()` 里增加 hook 即可
