# OpenClaw 接入适配

Clawguard 各模块对 OpenClaw 的改动统一存放于此目录（补丁、插件、配置），避免改动散落在各处。

## 重大改革（2026-08-20）：检索层去 bundle、插件化统一

**摒弃了什么**：
1. **bundle 补丁方案**（executePreparedToolCall SafeGuard 块，改 OpenClaw 源码）——已废弃（回退方案保留于 `patch_source/retrieval-guard/`，README 已标注）
2. **独立契约**（payload.text/tool）——统一为团队契约 `content/tool_name/source`（服务端 adapter 双兼容保留 text 路径）
3. **重复检查**（补丁 + 插件都调 content/check）——统一为插件单一转发

**新思路**：
- **OpenClaw 端零源码修改**：唯一接入是 `clawguard-adapter` 插件（全流程 hook 转发）
- **服务端分流**：`/v1/content/check` 只跑 Retrieval Guard（PIGuard）；IO Guard 管 input/output（`io_guard_context` 已 disabled）
- **契约统一**：content 阶段 payload 用 `content/tool_name/source`
- **版本适配**：插件 compat 已降级适配 2026.6.11；`before_agent_run` prompt 消费补丁按 6.11 移植（`patch_source/clawguard-adapter/`）

## 当前内容

**Retrieval Guard（检索内容安全）**：对 `web_search` / `web_fetch` 返回的外部内容做注入检测与提示词包装（A URL 白名单 → B PIGuard 检测 → C 包装），在工具结果进 AI 上下文前拦截。

OpenClaw 端接入：`clawguard-adapter` 插件的 `agentToolResultMiddleware` 转发 `/v1/content/check` 到服务端 Retrieval Guard adapter（PIGuard 拦截/包装，score 可见于隔离消息）。

- 端到端验证：见 [retrieval_guard 模块 README](../clawguard/modules/retrieval_guard/README.md)

**Audit（审计数据源）**：插件把输入 / 工具调用 / 输出事件上报 Clawguard `/v1/audit/event`（sessionKey→session_id、runId→trace_id），落盘见 [audit 模块 README](../clawguard/modules/audit/README.md)。

- 插件文档：[plugins/clawguard-session-test/README.md](plugins/clawguard-session-test/README.md)

**Clawguard Adapter（输入、工具内容和输出防护）**：通过四个 OpenClaw Hook 将用户输入、`web_search` / `web_fetch` 结果和最终回复接入统一 Clawguard FastAPI。

- Hook：`before_agent_run`、`after_tool_call`、`tool_result_persist`、`message_sending`；
- 统一接口：`/v1/input/check`、`/v1/content/check`、`/v1/output/check`；
- 插件源码和配置：[plugins/clawguard-adapter/README.md](plugins/clawguard-adapter/README.md)。
- OpenClaw 兼容补丁：[patch_source/clawguard-adapter/README.md](patch_source/clawguard-adapter/README.md)，用于应用输入 `rewrite`；工具结果竞态由插件的原生中间件修复。

## 目录结构

| 目录 | 用途 | 状态 |
|---|---|---|
| `patches/` | `.patch` 差异文件 + 一键应用脚本 | Retrieval Guard 已使用 |
| `patch_source/` | 每个模块一个子文件夹，放「补丁说明 + 原始源文件 + 修改后源文件」 | Retrieval Guard 已使用 |
| `plugins/` | OpenClaw 插件（四 Hook 安全适配、审计数据源等） | Clawguard Adapter、Audit 已使用 |
| `config/` | OpenClaw 配置片段 | 预留 |

其他模块接入时，按各自约定补充到对应子目录。
