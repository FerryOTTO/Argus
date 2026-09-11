# Argus x LLMGate 对接方案（终端集控版）
> 阅读对象：Argus 客户端 + 桌面端工程师；服务端由同学维护，本文只写客户端要做的事。
> 契约来源：E:\tiaozhanbei\MAC\LLMGate\REMOTE.md + e2e_telemetry_test.sh + configs\config.yaml。
> 目标：个人版不上报不拉配置；企业版用邀请码激活后被 LLMGate 纳管。日期 2026-09-09。
> 三端默认地址：LLMGate http://127.0.0.1:8080，Argus http://127.0.0.1:8000。

## 1. 现状盘点

| 端 | 位置 | 现状 |
|---|---|---|
| LLMGate 服务端+控制台 | E:\tiaozhanbei\MAC\LLMGate，Go+Gin+SQLite+Vue | 遥测6接口+OpenAI兼容网关+管理台已实现，见 REMOTE 第3/7节 |
| Argus 本体 | E:\tiaozhanbei\MAC\Argus，Python FastAPI | 有 /v1/audit/* 和 /v1/desktop/runtime，无 LLMGate 同步逻辑 |
| 桌面壳 | E:\tiaozhanbei\MAC\argus-desktop，Electron+Vue | 个人工作台读本地8000，企业版内嵌 OpenGuard，未接 LLMGate |

结论：缺一块企业同步器，建议放在 Python 侧（能读写审计 JSONL 和各配置文件），Electron 只展示不存 token。

## 2. LLMGate 协议速览

| # | 接口 | 鉴权 | 用途/频率 |
|---|---|---|---|
| 1 | POST /telemetry/v1/register | body 带 registration_code | 换 token+LLM 凭据，仅一次明文；重复调用=轮换 |
| 2 | POST /telemetry/v1/heartbeat | Bearer 遥测 token | 30-60s 一次；120s 无心跳判离线；回 config_pending+config_version |
| 3 | GET /telemetry/v1/config | Bearer | 仅 pending 时拉；空串=收回=不动作 |
| 4 | POST /telemetry/v1/config/applied | Bearer | 成功才回执；超前 409；失败不回执 |
| 5 | POST /telemetry/v1/report | Bearer | 60s 上报 token_usage_delta+security_alerts_delta+alert_samples(<=100)；200 才清零 |
| 6 | POST /telemetry/v1/audit/events | Bearer | 60s 批量 <=500 按时间升序；200 才推进游标 |
| 7 | GET/POST {llm.base_url}/v1/models, /chat/completions | Bearer llm.api_key | Agent 走企业网关；越权 403 model_not_permitted |

三种凭据不可混用：遥测 token、管理员 JWT、LLM key。时间一律 ISO8601 UTC。错误体 {error:{message,type,code}}。

### 注册
请求 {registration_code, hostname, os_info, agent_type, agent_version, argus_version}，agent_type 须与建终端一致（现仅 openclaw，否则 409）。
成功返回 {terminal_id, terminal_name, agent_type, token, llm:{api_key_id, api_key, base_url, enterprise_name}}。
base_url=系统根地址+/v1；enterprise_name 供展示；key 权限=开放模型白名单。

### 心跳/拉配置/回执
心跳 body 全可选，非空才更新；响应 {status, server_time, config_pending, config_version}。
拉配置响应 {terminal_id, config_version, config(字符串 JSON), config_updated_at, config_pending, config_applied_version}。
回执 {config_version:N}，管理台对照 version/applied 显示同步状态。

### report（增量）
token_usage_delta=窗口 LLM Token 合计；security_alerts_delta=动作非 allow 次数；alert_samples 只留存不计数；
服务端回 token_usage_total/alert_count_total 可对账。串行发送，失败保留窗口下轮合并重发。

### audit/events（全量+幂等，整批全有或全无）
字段与本地 AuditEvent 同名：event_id/trace_id/session_id/user_id/timestamp/stage/source_module/action/risk_score/reason/content/metadata。
event_id 终端内唯一，服务端按 (terminal_id,event_id) 去重；action 仅 allow/block/rewrite/human_review；
任一条非法整批 400 带 events[i] 索引，不入库；修好整批重发。本地 JSONL 永远权威只追加，集控保留默认 90 天。
## 3. 配置包 v1 映射（REMOTE 4.6 全量，已生效项）

包是 partial 增量：只含被改键，未出现=保持本地。7 条铁律：schema_version=1 才收（否则拒收不回执）；
递归深合并；标量覆盖（含空串/0）；数组整体替换；config="" 不动；未知键忽略+warn；
modules.tool_guard.api_key 空不覆盖、非空才覆盖。

| 包前缀 | 本地载体 |
|---|---|
| modules.* | configs/modules.yaml 的 modules.* 段；注意 tool_guard 有 TOOL_GUARD_LLM_* env 优先，写生效层 |
| io_guard_policy.* | IO Guard default_policy.json 顶层一一对应（含 decision_thresholds/语义检测/附件抽取，audit.* 2 键见审计） |
| access.* | auth_gateway 读的 ARGUS_* 环境变量或等价持久源（mode/风险联动/隔离阈值） |
| access_rules.users/resources | users.txt / resources.txt 原文整体替换，空串=不覆盖 |
| retrieval.* | whitelist.yaml / b_injection/config.yaml / c_prompt/config.yaml（白名单数组整体替换） |
| integration.* | OpenClaw 插件 entries.argus-adapter.config.*（地址/超时/fail_mode/受保护工具） |

分组速查：IO 开关 5 项、IO 策略约 20 项、ToolGuard 约 10 项、Retrieval 约 11 项、访问控制 13 项+2 规则文件、
审计 4 项、沙箱 3 项、人工复核 1 项、集成 7 项。实现按 REMOTE 4.6.3 逐键白名单合并，未列出键一律忽略。

## 4. 推荐架构：Python 同步器 + Electron 纯展示

Electron main 不存密钥只做窗口透传；renderer 只调本地 8000，不直连 8080；遥测 token 永不进 localStorage。
Python 新增 remote_sync 包，复用文件权限+日志+重试，能直接 tail 审计 JSONL 并落盘配置。

建议新增：

```text
argus/remote/client.py         register/heartbeat/get_config/applied/report/audit_events（10s 超时+指数退避）
argus/remote/store.py          读写 config/remote.json + cursors.json（原子写+备份）
argus/remote/config_apply.py   schema 校验+白名单深合并+数组替换+备份回滚+各载体落盘
argus/remote/counters.py       report 窗口累计，200 才清零
argus/remote/audit_tail.py     tail 审计 JSONL，按 event_id 游标分批<=500 升序发送
argus/remote/scheduler.py      后台线程：heartbeat 45s / report 60s / audit 60s / config 重试 5min
argus/api/remote_router.py     GET /v1/remote/status, POST /v1/remote/register|sync-config|unbind
```

本地状态 config/remote.json（权限 0600）：remote{base_url, registration_code(一次性用完即清), token, terminal_id,
terminal_name, enterprise_name, heartbeat/report 间隔, config_applied_version} + llm{api_key, base_url, enterprise_name}。
游标 runtime/remote/cursors.json：{report_window_started_at, token_delta, alerts_delta, audit_last_event_id,
last_heartbeat_at, last_report_at, last_audit_at}，只在 200 后推进。

Electron 新增本地接口（走 8000）：

```text
GET /v1/remote/status   -> {mode, bound, online, enterprise_name, terminal, versions, llm:{base_url}, totals, sync, queue}
POST /v1/remote/register {base_url, registration_code}
POST /v1/remote/sync-config
POST /v1/remote/unbind
```

## 5. 核心流程

1. 管理员控制台添加终端 -> 得 registration_code（重发旧码失效）。
2. 企业版输入码 -> Python register -> 存 token+llm -> 进循环。
3. 每 45s heartbeat -> config_pending 则 GET config -> 校验 -> 备份 -> 合并落盘 -> applied；失败不回执+告警+5min 重试。
4. 每 60s report（200 清零）+ audit/events（200 推进游标），串行+退避 1s->60s。
5. Agent LLM 改走 llm.base_url + llm.api_key；先 GET /v1/models 校验。
6. 401 token 失效 -> 停心跳，用保存码重注册一次；仍 401 -> 离线告警等管理员重发码。
## 6. 数据口径

终端名/描述/Agent类型/绑定用户=建终端录入；计算机名/版本=注册+心跳更新；在线=120s 内有心跳；
Token 总量/预警总量=report 累加；配置状态=version vs applied；终端审计明细=audit/events 全量。
个人版不上报，管理台看不到该机。

## 7. 异常矩阵（照 REMOTE 第 8 节实现）

注册码错 401 等重发；agent_type 409 查声明；token 401 重注册仍败则离线；LLM 401 查吊销/重注册；
LLM 403 换开放模型内模型；网络断开退避 1s..60s，恢复补心跳+滞留窗口；report 5xx/429 保留窗口合并重发；
audit 400 按索引修好整批重发不推进游标；audit 网络/5xx 保留游标重试；配置失败不回执+5min 重试；
schema 非 1 拒收不回执。

## 8. 分阶段开发

- P0 注册与安全存储：remote.json 0600、注册码用完即清、renderer 不落地 token、备份回滚、跑通 e2e 1-3。
- P1 心跳+配置同步：45s 心跳、pending 拉取、白名单合并、applied、status 接口、跑通 e2e 4-7。
- P2 report+审计上传：窗口累计、tail 游标、分批串行、200 推进、跑通 e2e 8-10。
- P3 企业版 UI+LLM 切换：设置注册页、状态面板、模型列表配额展示、解绑；管理台核对总量与明细。
- P4 联调 hardening：断网/吊销/409/400/大批量/并发上报、老包兼容、日志告警文案。

## 9. 联调与验收

先跑同学 e2e_telemetry_test.sh，再按 REMOTE 第 9 节 curl 走一遍建终端->注册->心跳->下发->拉取->回执->上报->查终端。
验收：管理台在线；下发 1min 内 applied 一致；report totals 对上；终端审计可按 terminal/stage/action/risk 筛选导出；
吊销后离线并提示重绑；重复上传不产生重复行。

## 10. 安全红线（P0 必须遵守）

1. token/LLM key 不进前端 localStorage，不打日志，不外发。
2. 注册码一次性，用完内存+落盘清除；重复注册会轮换旧凭据，需二次确认。
3. 配置先备份，失败回滚，成功才回执；未知键忽略，schema 非 1 拒收。
4. 审计本地权威，失败不删不推进；event_id 复用本地 uuid5。
5. 生产必改：jwt_secret（默认 change-me-in-production）、admin123、CORS * 收紧、SQLite 备份。

## 11. 风险与待确认（需同学回复）

1. Token 统计口径：经网关 prompt+completion 由谁统计？直连模型 report 是否填 0？
2. LLM key 轮换后，OpenClaw 插件 base_url/key 如何热更新？谁负责重启/推送？
3. TOOL_GUARD_LLM_* env 优先于 yaml，配置包写 yaml 是否生效？以哪个为准？
4. 企业版入口最终是 LLMGate 控制台、OpenGuard，还是共存？建议共存：OpenGuard 管聊，LLMGate 管终端/配额/审计，不重复造账号。
5. 企业面板只读聚合+审计筛选，不给 admin JWT，个人/企业数据隔离是否接受？
6. 审计保留 90 天、单对象 64KB、单批 500 在演示量下是否够用？
7. agent_type 仅 openclaw，企业版是否需新增类型？服务端加白名单即可，协议不变。

## 12. 下一步

1. 确认 11 章的 1/2/4（统计口径、LLM 热更新、企业版入口）。
2. 给一个测试 registration_code + 可用 base_url。
3. 按 P0->P1 先做 Python 同步器+状态接口，再做桌面企业版展示，不动个人版链路。
