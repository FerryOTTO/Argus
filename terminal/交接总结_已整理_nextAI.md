# Argus V2.1 工作交接总结（已整理 NextAI 版）

> 仓库：E:/tiaozhanbei/MAC/Argus（git 真仓库） 远端 https://github.com/WT-ever/ClawguardV2.1.git
> 分支：main 长期，module/xxx 短期，当前 main=origin/main 5417039，48 提交，241 测试通过
> 拉取：git fetch origin && git merge origin/main --ff-only

## 一、链路
用户 -> OpenGuard:3000 -> Bridge:18080 -> OpenClaw:18789 -> Argus:8000
- OpenGuard openguard/original FastAPI+JWT
- Bridge node bridge.js Ed25519
- OpenClaw CLI 2026.6.11 openclaw gateway run
- Argus argus/ FastAPI+uvicorn

## 二、启动顺序
1. openclaw gateway run (daemon, 需 stop 否则 18789 占用)
2. py -m uvicorn argus.api.main:app --host 127.0.0.1 --port 8000
3. py -m uvicorn main:app --host 127.0.0.1 --port 3000 (在 openguard/original)
4. node bridge.js (在 openguard/original, 依赖 OpenClaw ready)

## 三、已修复坑
- apscheduler sse_starlette 缺失 -> pip install
- starlette 1.6.0 移除 on_startup -> 降级 starlette 0.41.3 + sse-starlette 2.4.1
- bridge.js protocol 3 -> 4 已合入 main

## 四、测试账号
- test_admin top_secret usr_bKIkVA5fIYbk70oH
- test_secret secret usr_tgG0tp7rB2PC59tY
- test_internal internal usr_GM6CllBEfyjvON19
- test_public public usr_sZdr4JGexJ2hDQ5p
- 规则文件 argus/modules/access_control/original/rules/users.txt
- 新注册默认 internal，需在 users.txt 配等级并重启 Argus
- 验证：query_weather 全放行, read_file>=internal, write_file>=secret, execute_bash>=top_secret

## 五、插件
- 源码 openclaw_adapter/plugins/argus-adapter (compat >=2026.6.11)
- 部署 C:/Users/admin/.openclaw/extensions/argus-adapter dist+manifest+package.json
- 配置 openclaw.json allow argus-adapter + hooks.allowConversationAccess=true
- 备份 openclaw.json.bak-20260830-181454
- 四阶段: before_agent_run->/v1/input/check, before_tool_call->/v1/tool/pre_check, tool_result_persist->/v1/content/check, message_sending->/v1/output/check

## 六、审计联动 risk_link.py
- AuditRiskMonitor 读 JSONL 按 user/session/300s 评分 probe_likely
- DynamicLinePolicy penalty 0-2 动态提级 -> human_review
- penalty 参数向后兼容，fail-open，ARGUS_AC_RISK_LINK=0 关闭
- 注意：反复 block 会累积，需清 runtime/audit/audit-events.jsonl

## 七、测试
- py -m pytest tests/ -q 241 passed
- py tests/test_access_control.py 32 用例
- py -m pytest tests/test_access_control_risk_link.py -v 19 用例
- scripts/demo_risk_link.py

## 八、周报 E:/tiaozhanbei/MAC/v6/本周报告.md

## 九、待办
1. 四阶段拦截验收（输入注入、工具越权、web隔离、输出脱敏）
2. 文档版本 2026.4.2 -> 2026.6.11
3. 确认 failMode closed 稳定
4. routes.py on_startup 升级

---
## 原文（UTF-8 已校验）
`
以下是我这一路工作全过程的交接总结，纯文字，直接复制给下一个 AI。
仓库位置：E:\tiaozhanbei\MAC\Argus（这是真正的 git 仓库，根目录有 .git） 注意：E:\tiaozhanbei\MAC\Argus-main 是旧解压目录，不要用。 远程仓库：[https://github.com/WT-ever/ClawguardV2.1.git](https://github.com/WT-ever/ClawguardV2.1.git) 分支规范：main 为长期分支，各成员用 module/xxx 短期分支，合入后删除。 当前 main 已同步到 origin/main 最新（提交 5417039 fix: preserve audit and media plugin initialization），48 个提交已合并，全量测试 241 个全部通过。 拉取命令：git fetch origin，然后 git merge origin/main --ff-only。 我之前的 module/access-control 分支上 20 个提交已经全部进入 origin/main，该分支相对 origin/main 已无独有内容。
用户 → OpenGuard(:3000) → Bridge(:18080) → OpenClaw(:18789) → Argus(:8000)
- OpenGuard：用户认证 + Web 聊天页面，在 openguard/original/ 目录，FastAPI + JWT。
- Bridge：node bridge.js，用 Ed25519 设备认证连 OpenClaw WebSocket。
- OpenClaw：CLI 版（npm 全局安装），版本 2026.6.11，命令 openclaw gateway run。
- Argus：统一安全服务，argus/ 目录，FastAPI + uvicorn。
启动顺序：先 OpenClaw，再 Argus 和 OpenGuard，最后 Bridge（Bridge 依赖 OpenClaw ready 才能握手）。
1. OpenClaw（后台）： openclaw gateway run 注意：这个命令会 daemon 化，后台命令进程退出后网关进程仍存活。要彻底停必须用 openclaw gateway stop。重启前务必先 stop，否则端口 18789 被旧实例占用，新实例会报 gateway already running。
2. Argus（后台）： cd /e/tiaozhanbei/MAC/Argus && py -m uvicorn argus.api.main:app --host 127.0.0.1 --port 8000 注意：python 命令要用 py（Windows 上 python 指向 Python 2.7，py 才是 Python 3.13）。
3. OpenGuard（后台）： cd /e/tiaozhanbei/MAC/Argus/openguard/original && py -m uvicorn main:app --host 127.0.0.1 --port 3000
4. Bridge（后台）： cd /e/tiaozhanbei/MAC/Argus/openguard/original && node bridge.js
1. OpenGuard 缺依赖 apscheduler、sse_starlette，需 py -m pip install apscheduler sse-starlette。
2. 版本不兼容：本机 fastapi 0.115.3 配了 starlette 1.6.0，启动 OpenGuard 报 TypeError: Router.init() got an unexpected keyword argument 'on_startup'。因为 starlette 1.x 移除了 on_startup。已降级： py -m pip install "starlette>=0.40,<0.42"（装成 0.41.3） py -m pip install "sse-starlette>=1.6,<3"（装成 2.4.1，与 starlette 0.41 兼容）
3. Bridge 协议版本：老代码 bridge.js 用 minProtocol:3/maxProtocol:3，本机 OpenClaw 2026.6.11 要求 protocol 4。已把 bridge.js 里两处改成 4（token 模式和 Ed25519 模式），此修复已合入 main。当前 main 里的 bridge.js 已经是 4。
在 OpenGuard 数据库创建了 4 个不同等级账号，并同步到了访问控制规则文件：
- test_admin → top_secret，id=usr_bKIkVA5fIYbk70oH
- test_secret → secret， id=usr_tgG0tp7rB2PC59tY
- test_internal → internal， id=usr_GM6CllBEfyjvON19
- test_public → public， id=usr_sZdr4JGexJ2hDQ5p 访问控制规则文件：E:\tiaozhanbei\MAC\Argus\argus\modules\access_control\original\rules\users.txt 新注册的 OpenGuard 用户 security_level 都是 internal（auth.py register_user 里硬编码），要分等级需在 users.txt 里给对应 usr_xxx 配等级，然后重启 Argus（规则在启动时加载，无 reload 接口）。 访问控制等级阶梯已验证正确：query_weather 四级全放行；read_file 需 internal；write_file 需 secret；execute_bash 需 top_secret。
插件源码：E:\tiaozhanbei\MAC\Argus\openclaw_adapter\plugins\argus-adapter 插件本就是为 2026.6.11 构建（package.json 里 compat.pluginApi >=2026.6.11），文档《真实链路接入方案.md》说按 2026.7.1-2 构建是过时的。 部署位置：C:\Users\admin.openclaw\extensions\argus-adapter\（注意是 extensions 不是 plugins） 部署内容：dist/、openclaw.plugin.json、package.json、README.md 关键坑：只放 dist+manifest 会报 plugin not found，必须带 package.json，OpenClaw 靠它发现插件入口。 配置：C:\Users\admin.openclaw\openclaw.json 的 plugins 段，加了： allow: ["argus-adapter"] entries.argus-adapter: {enabled:true, config:{argusUrl:"[http://127.0.0.1:8000](http://127.0.0.1:8000/)", failMode:"closed", protectedTools:[...]}, hooks:{allowConversationAccess:true}} 关键坑：不加 hooks.allowConversationAccess=true，before_agent_run 和 agent_end 会被阻止（日志报 typed hook blocked），输入检查失效。 配置修改前已备份：openclaw.json.bak-20260830-181454 插件覆盖四阶段：before_agent_run→/v1/input/check；before_tool_call→/v1/tool/pre_check；tool_result_persist→/v1/content/check；message_sending→/v1/output/check。 验证：openclaw plugins list 显示 argus-adapter enabled；启动日志 Argus API is healthy。
文件：E:\tiaozhanbei\MAC\Argus\argus\modules\access_control\risk_link.py
- AuditRiskMonitor：读审计 JSONL，按 user/session/时间窗(默认300秒)算风险评分，识别频发试探（block_count 达到阈值判定 probe_likely）。
- DynamicLinePolicy：按风险评分算 penalty(0-2)，动态提高资源所需等级，升级后本应拦截的请求转 human_review 二次审批。 auth_gateway.py 的 check_reason/check_v4 增加了向后兼容的 penalty 参数（默认0，不影响原调用）。 access_control_adapter.py 集成联动：原始判定→审计风险评估→防线升级重判→human_review。审计不可用时 fail-open；可用环境变量 ARGUS_AC_RISK_LINK=0 关闭。 注意：测试时如果同一个用户反复触发 block，审计里会累积事件导致风险评分升高，进而触发防线升级（会误伤后续测试）。测完要清审计文件：E:\tiaozhanbei\MAC\Argus\runtime\audit\audit-events.jsonl（该目录不提交 git）。
- 全量测试：cd /e/tiaozhanbei/MAC/Argus && py -m pytest tests/ -q（241 passed）
- 访问控制测试：py tests/test_access_control.py（脚本式测试，32 用例）
- 审计联动测试：py -m pytest tests/test_access_control_risk_link.py -v（19 用例）
- 演示脚本：scripts/demo_risk_link.py（启动 Argus 后跑，演示访问控制+审计联动） 测试文件都在 E:\tiaozhanbei\MAC\Argus\tests\。
已写入 E:\tiaozhanbei\MAC\v6\本周报告.md，包含本周目标、代码同步、系统启动、测试账号、插件安装、问题清单（P0/P1/P2）、下一步建议。
系统已全部启动过且健康，但我这边所有后台服务进程已停止（可能重启过机器），需要重新按第三节顺序启动。 待办：
1. 按《真实链路接入方案.md》做四阶段安全拦截验收（用聊天实测输入注入拦截、工具越权拦截、web内容隔离、输出脱敏）。
2. 文档《真实链路接入方案.md》里写的 OpenClaw 版本 2026.4.2 已过时，实际是 2026.6.11，需更新。
3. 确认插件 failMode（当前 closed）在演示时 Argus 服务稳定。
4. OpenGuard 的 routes.py 还在用废弃的 on_startup 写法，后续可升级代码。
`
