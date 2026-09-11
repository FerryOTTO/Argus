# Clawguard Adapter compatibility patch

适用版本：OpenClaw `2026.6.11`（npm 包版本 `2026.6.11`）。

该补丁已按 `2026.6.11` 的 `selection-*.js` bundle 结构重新定位，作用与原
`2026.7.1-2` 版本一致：让 `before_agent_run` 对 `event.prompt` 的安全改写成为
实际送入模型的文本。

Clawguard 输入接口支持 `rewrite`，但 OpenClaw 的 `before_agent_run` 标准返回值只有
`pass/block`，默认不会消费 Hook 对 `event.prompt` 的修改。本目录的脚本给当前
OpenClaw embedded-agent bundle 加一层最小兼容：Hook 返回 `pass` 后，以修改后的
`event.prompt` 作为本次模型输入，原始用户消息仍保留在会话中用于审计。

工具结果的异步缓存竞态不再由 bundle 补丁处理。插件 `0.4.0` 已注册 OpenClaw
`agentToolResultMiddleware`，会在工具结果进入模型前等待 Clawguard 内容检查完成。

以管理员 PowerShell 执行：

```powershell
cd openclaw_adapter\patches\scripts
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\apply-clawguard-adapter-patch.ps1
```

脚本会自动定位全局 npm 的 OpenClaw，验证唯一的 6.11 `selection-*.js` 目标，
创建一次 `.clawguard.orig` 备份，应用补丁并运行 `node --check`。重复运行是幂等的。
OpenClaw 升级后 bundle 名称可能改变，应重新验证并应用脚本，不能直接复用旧备份。
