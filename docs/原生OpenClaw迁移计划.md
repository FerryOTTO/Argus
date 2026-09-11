# 原生 OpenClaw 迁移计划：聊天全走原生，界面只做管理

> 状态：计划中。做完一步勾一步。
> 约定：个人版 = 本机单人，无登录；企业版 = 服务器身份 + 登录令牌。
> 端口约定：`:8000`=Argus，`:18789`=原生 OpenClaw 网关，`:3000`=OpenGuard（待删），`:18080`=Bridge（待删），`:8080`=LLMGate 企业服务器。

## 0. 要干什么（一句话）

个人版、企业版的聊天都搬到原生 OpenClaw 上；桌面端（`argus-desktop`）只留配置 / 审计 / 小窗；
删掉 OpenGuard（`:3000`）和 Bridge（`:18080`）；身份改由 LLMGate 服务器统一存发。

```
现在：桌面聊天 → :3000(OpenGuard) → :18080(Bridge) → :18789(OpenClaw) → :8000(Argus)
以后：原生聊天 → :18789(OpenClaw + argus-adapter插件) → :8000(Argus)
      桌面端只做：改配置(GET/PUT :8000/v1/local/config) + 看审计 + 小窗
```

## 1. 现状（已核对文件，勿凭印象改）

| 东西 | 在哪 | 说明 |
|---|---|---|
| 拦截真相 | `Argus/openclaw_adapter/plugins/argus-adapter/src/index.ts` | 7个钩子：`before_agent_run`(输入) / `before_tool_call`(工具前，真tool名+参数) / `agent_tool_result_middleware`+`after_tool_call`+`tool_result_persist`(工具结果) / `message_sending`+`reply_payload_sending`(输出)。跟用哪个聊天UI无关 |
| 插件身份（现在是猜的） | `index.ts:414-438` | `isOwner/senderIsOwner + channel(webchat/control-ui)` → 内外身份；`user_id ← senderId/agentId/sessionId`；input检查带 `role_level: isOwner?3:0` |
| 插件配置 | `openclaw.plugin.json` + `openclaw.config.example.json5` | `argusUrl/timeoutMs/failMode(closed)/protectedTools` 等；`failMode` 默认 `closed`（8000挂了就拦，不裸奔） |
| 等级规则 | `argus/modules/access_control/original/rules/users.txt` | 格式 `用户名\|等级\|特例`；等级 `public1/internal2/secret3/top_secret4`；特例如 `*`、`!tool:write_file`、`tool:query_weather` |
| 资源规则 | `.../rules/resources.txt` | 格式 `路径模式\|所需等级\|flat/inherit/override`；默认未匹配资源拦截（零信任） |
| 判定入口 | `auth_gateway.py: check()/check_reason()/check_v4()` | `check_v4` 给统一接口用，支持 `penalty`（审计联动动态收紧） |
| 用户同步（待删） | `openguard/original/main.py:41-70 lifespan` | 开机把 OpenGuard DB 用户写入 access_control；`RuleStore._lookup_db_user(auth_gateway.py:236)` 运行时回查 `openguard/original/data/auth.db` |
| 个人版登录（待删） | `openguard/original/routes.py:75 /auth/desktop` | 仅本机+`X-Argus-Desktop` 头；`PersonalWorkspace.vue:298` 调用后存 `argus_token` |
| Bridge能力（待删） | `openguard/original/bridge.js` | Ed25519握手+持久WS；按session前缀防串消息；HMAC客户端认证；`PUT/DELETE /api/agents/:id/files/*` 装技能文件；`POST /api/agents` 建agent |
| 桌面拉起（要改） | `argus-desktop/src/main/daemon.js:180-245` | 拉起4进程：8000/18789/18080/3000；健康检查 `checkPort` |
| 小窗三探针（要改） | `EnterpriseMini.vue:27-36`、`MimoCodeLanding.vue:331-333` | 查 `8000/18789/18080` 的 `/health`，拼 `F:ok/down O: B:` |
| 企业用户表（要加字段） | `LLMGate/migrations/001_init.sql` 的 `users` 表 | 现只有 `id/username/password_hash/email/role/is_active`，**无等级字段** |
| 企业终端表（已有） | `LLMGate/migrations/007_terminals.sql` 的 `agent_terminals` | `bound_user_id` 已有；双计数器 `config_version/config_applied_version`；迁移用 `store/RunMigrations` 按文件名顺序执行 |
| 企业下发链路（不动） | `LLMGate/internal/handler/admin_terminal.go` 等 | Admin PUT配置 → `config_version+1` → 终端心跳发现pending → 拉包 → 回执；`desired_config` 是不透明文本 |

## 2. 身份方案（核心，4步）

### 2.1 服务器存人：`users` 表加 2 个字段（迁移 `011_identity.sql`）

> 已核对：`must_change_password` 在 `005_password_policy.sql` 已加，本次**不再加**，只加下面两个。

```sql
ALTER TABLE users ADD COLUMN security_level TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE users ADD COLUMN specials TEXT NOT NULL DEFAULT '';
```

- 开工前先跑：`grep -rn "security_level\|specials" LLMGate/migrations/` 确认无冲突，再写 011。

- `security_level` 取值：`public/internal/secret/top_secret`，与 `auth_gateway._normalize_level` 完全对齐。
- `specials` 原样存 `users.txt` 第三列写法（逗号分隔，如 `*,!tool:write_file`），终端原样写入本地规则，零转换。
- `users.txt` 现有 100+ 行里大量 `usr_*/agent_*` 测试账号：**只搬 5 个语义账号**（`adminuser/top_secret`、`user_public/public`、`user_internal/internal`、`user_secret/secret`、`user_admin/top_secret` + `auditor_01` 特例），其余测试垃圾不进服务器。
- `resources.txt` 不进服务器，仍是本地文件（它是机器相关的路径规则）。

### 2.2 登录发令牌：复用 LLMGate 现有登录

- LLMGate 已有 `users` + 登录/JWT（`internal/auth`）。企业用户在桌面企业登录框登录 → 服务器返回令牌，令牌载荷加 `security_level + specials`。
- 桌面存令牌（`localStorage`，沿用现在存 `argus_token` 的位置）。
- 校验规则：`is_active=1` 才能登录；等级由管理员在后台改，不由用户自选。
- 个人版：跳过本步，写死 `user_id=desktop-local, level=internal`（与 `users.txt:87` 现有行一致）。

### 2.3 聊天带身份：插件只改身份来源，不改判定

- 文件：`openclaw_adapter/plugins/argus-adapter/src/index.ts` 的 `before_agent_run` 身份段（约414-438行）。
- 载体（定死，不再二选一）：**终端本地身份文件**。企业登录成功后，桌面端把 `user_id/security_level/specials` 写到本机一个只读小文件
  （如 `argus/identity.json`）；插件 `before_agent_run` 每次读该文件取身份。为什么不用请求元数据/请求头：
  原生 UI 的消息格式不受我们控制，塞元数据可能被网关洗掉；读本地文件最稳，不依赖上游。
- 降级规则（fail-closed，不回落猜测）：企业版下文件缺失/过期/损坏 → 按**最低等级 `public`** 处理并记审计，
  不再悄悄走老 owner/channel 猜测逻辑；个人版本地文件写死 `desktop-local/internal`。
- `GuardClient` 发给 `:8000` 的 `RequestIdentity` 不变（还是 `trace_id/session_id/user_id`），`access_control` 的 `check/check_reason` **一个字不用改**。
- 等级同步：终端每次应用企业下发配置时，把“等级表”一起写成本地 `users.txt` 增量。幂等要求：
  用 `add_user_rule` 逐条写（同名用户是**更新**不是追加，见 `RuleStore.add_user_rule:289` 先读 existing 再覆盖写回），
  多下发几次 `users.txt` 不能出现重复行，Step 1 验收时连下 3 次验证行数不变。

### 2.4 审计对上人

- 插件传什么 `user_id`，`:8000` 审计就记什么。不再出现以前“全是 owner / 全是 external”的情况。
- 企业端按 `user_id` 统计 token/告警，自然对齐。

## 3. 会话隔离（防对话泄露，跟着身份一起做）

- 问题：原生 OpenClaw 不分用户，聊天记录全放一起，换人登录能看到上一个人的记录。
- 主人定死：**网关插件侧做过滤**，桌面端管不到原生 UI 的会话列表。
  做法：`before_agent_run` 绑定 `sessionId ↔ user_id`（身份文件里的人）；后续消息只投递给绑定的用户，
  未绑定/换人登录看不到旧会话。企业版切用户时，桌面端同时重写本地身份文件并清空当前视图。
- 个人版：单人不做。
- 验收：A登录聊天 → 切B（身份文件换人）→ B 看不到A的记录。

## 4. 砍掉 :3000 和 :18080（清单制，一项项删）

| # | 删/改什么 | 文件 | 改后 |
|---|---|---|---|
| 4.1 | 拉起 3000/18080（留开关过渡） | `argus-desktop/src/main/daemon.js:180-200 startAll` | 加环境开关 `ARGUS_LEGACY_CHAIN=1`：默认只拉 `:8000`+`:18789`；开关开了才拉 3000/18080。个人版先切新链路，坏了一键切回老链路，不删代码只分叉 |
| 4.2 | 桌面聊天区 | `PersonalWorkspace.vue` | 聊天相关（`:3000` 的 `API_BASE`、WS、`/auth/desktop`）删除；保留审计页（调 `:8000` 的 `AUDIT_API_BASE` 不动） |
| 4.3 | 小窗 B 路 | `EnterpriseMini.vue`、`MimoCodeLanding.vue` | 健康检查只剩 F(`:8000`)+O(`:18789`)；`F:ok/down O:ok/down` |
| 4.4 | 开机同步用户 | `openguard/original/main.py:41-70` | 整段删除（openguard 整个目录退役，此为过渡） |
| 4.5 | DB回查 | `auth_gateway.py:236 _lookup_db_user` | 改为直接返回 `None`（不再读 `auth.db`）；函数壳保留防 import 报错 |
| 4.6 | openguard+bridge 退役 | `Argus/openguard/` | 先留档不删，改名 `openguard_retired_YYYYMMDD`；确认稳定两周后再删 |
| 4.7 | 桌面登录 `/auth/desktop` | `PersonalWorkspace.vue:298` | 个人版直接默认身份，不再请求；企业版走 LLMGate 登录（2.2） |

## 5. 技能文件接口重做（变简单，往后放）

- 原来：`PUT/DELETE :18080/api/agents/:id/files/*` 走网络装文件。
- 以后：都在本机，桌面端直接写文件到 `~/.openclaw/workspace[-agentId]/`（复用 `bridge.js:274-289 getAgentWorkspacePath/sanitizePath` 逻辑，防路径穿越）。
- 企业版做的时候加一条**归属校验**：A 用户只能写自己的 workspace 目录，`sanitizePath` 防穿越之外再比对目录归属，不允许跨用户写。
- 个人版先不做；企业版推技能时再补。

## 6. 企业配置下发（不动，只增一项）

- 现有链路不动：后台改 → `config_version+1` → 终端拉包 → 本地 `deep-merge` → 回执 `config_applied_version`。
- 新增：下发包里可带 `identity_table`（等级表），终端收到后调 `add_user_rule` 逐条写入（2.3）。
- 个人版 5 侧边栏 ↔ 企业 8 分组映射不动；`GET/PUT :8000/v1/local/config` 不动。

## 7. 分步实施顺序（一步一验）

> 前置：先清集成测试报告里的 P0 bug（配额失效/Anthropic 502/新模型需重启），有了回归基线再迁。
> 迁移期间 OpenClaw 版本钉死在 2026.6.11，不跟上游升级。

- [x] **Step 0 回归基线**（实测 2026-09-09，`llmgate.exe -config configs/config.yaml` @:8080，版本=源码已改+exe 09:59当天编）：
  P0 三项中 **BUG-02（Anthropic Content-Length 同步）✅、BUG-03（模型热加载 OnChange→LoadModels）✅ 已在运行版验证通过**——
  D5 新建模型 `/v1/models` 立即可见 ✅、L8 Anthropic 转发 200 且上游收到 system role ✅、N2 favicon ✅、M5 `/v1/remote/status` ✅；
  **BUG-01（用量落库 RecordUsage）✅ 代码已在运行版生效**（`usage_records` 30 条、当天有新行；F1 建配额 ✅、L10 用量 ✅），
  但 F4（429）本次被测试脚本中途删 provider 误杀——删的是软删除 `is_active=0` + 热加载真生效，路由表当场清空，
  后面 L/E/F 全 404。已定位：旧脚本那段"中途清理"是无热加载时代的残留，正确做法是终局统一清理；
  修复脚本后重跑 **76 项 70 过，仅剩 6 项非 P0**：C5/C6/C7（多用户自助口径待定，P1）、L2（SSE 大小写 `mock` 断言，脚本问题）、
  I8/I9（content 传字符串 vs 服务端要对象，脚本问题，服务端行为正确）。P1 口径（BUG-04/05）等你拍板再动。
- [x] **Step 1 服务器人表**：`011_identity.sql`（只加 `security_level/specials`，005 的 `must_change_password` 不重复加）
  + `model/user.go` 加字段 + `user_store.go` 的 Create/Update 跟进。验：临时库跑通，新用户默认 `internal/''`（已验 ✅，本机无 Go 工具链，`go build` 未跑，上线前在有 Go 的机器补跑一次）。
- [x] **Step 2 登录令牌带等级**：`Claims` 加 `security_level/specials`（`GenerateToken` 写入、`RefreshToken` 保留）；
  `Login` + `SSOCallback` 返回体带等级；`admin_user` 建/改用户支持等级（非法值回落 `internal`）；SSO 自建默认 `internal`。
  验：11 项静态检查全过 ✅（本机无 Go 工具链未编译，上线前补跑 `go build`）。
- [x] **Step 3 插件读身份文件**：新建 `src/local-identity.ts`（读 `~/.openclaw/argus/identity.json`，
  `ARGUS_IDENTITY_FILE` / 插件 `identityFile` 可覆盖；缺失/损坏返回 null → 最低 public fail-closed）；
  `index.ts before_agent_run` 改读文件（`role_level` 按 public1/internal2/secret3/top_secret4，`metadata` 带 `identity_source/security_level`；
  `identity_correlation_quality` 改 `identity_file/fallback`）；`types.ts` + `openclaw.plugin.json` 加 `identityFile` 配置项；
  `dist/` 已重编。验：`tsc` 零错，55/55 全过 ✅（含新增 `local-identity.test.mjs` 6 项；3 个旧用例改用 fixtures 身份文件）。
  注意：`internalChannels/ownerDataScopes` 配置项保留（secret/top_secret 照旧给 internal scope），老 owner/channel 猜测逻辑已删。
- [x] **Step 4 会话隔离**：插件侧 `before_agent_run` 做 `sessionId ↔ user_id` 绑定——同一 session 首次使用的用户占绑定，
  换人用同一 session 直接 block（`session_owner_mismatch`，提示新建会话）；`userId` 为空的 fail-closed 回落不占绑定；
  新会话不受影响。验：`tsc` 零错，59/59 全过 ✅（新增 `session-isolation.test.mjs` 4 项：同人复用过 / 换人同会话拦 / 换人新会话过 / 回落不占位）。
- [x] **Step 5 砍 3000/18080**（个人版先行，`ARGUS_LEGACY_CHAIN=1` 一键回滚）：
  `daemon.js` 默认只拉 8000+18789（`isLegacyChain()` 开关）；`index.js daemon-status` 加 `legacy` 字段，
  新链路下不再等 18080；`MimoCodeLanding` Bridge 检查项标 `legacyOnly` 跳过；`EnterpriseMini` 只看 F+O，
  18080 活着才显示 `B:ok(legacy)`；`PersonalWorkspace` 聊天区/会话列表/WS 整段停用（老代码已删，
  回滚用 git 恢复本文件），只留审计页 + 输入框改复制占位；`BentoCards/DaemonConsole` 去 Bridge 展示；
  `Start-ArgusDesktop.ps1` 同开关。验：`vite build ✓ built in 2.37s` ✅，
  剩余引用全是老链路注释/日志/过渡探针，无实际调用。
- [x] **Step 6 补技能本地写文件**：新建 `argus/api/skills_routes.py`（`PUT/DELETE /v1/local/skills/files` + `GET /v1/local/skills/workspace`），
  已挂到 `main.py`。语义与 Bridge 对齐（1MB 上限、`workspace[-agentId]` 落点、防穿越）+ 归属校验
  （`xxx-agent` 归 `xxx`；`main` 仅特例 `*` 运维可写）。验：TestClient 进程内 9/9 ✅
  （自写/落点/穿越拦/跨用户拦/main 保护/运维写/删探针/删测试/删缺失）。
  注意：线上 `:8000` 是旧进程（新路由 404），重启新版才生效；测试残留目录已清。
- [x] **Step 7 回归验证**（实测，2026-09-09，8000 活着、OpenClaw 钉死 2026.6.11）：
  ①输入 benign→allow ✅ / 身份 trace 回显 ✅；②工具 `user_public+exec→access_control 直接 block 短路` ✅、
  `user_internal+web_search→放行进 tool_guard` ✅；③内容/输出 benign 检查 ✅；④关断 fail-closed ✅
  （死端口前提真 + 8000 活着 + 产物 `failMode=closed` + catch 分支 block 逻辑在）；⑤插件全套件 59/59 ✅，
  依赖 openclaw==2026.6.11 未动；⑥桌面 `vite build ✓` ✅。人工确认弹窗（requireApproval）在原生 UI 的渲染、
  Go 侧 `go build`，留到有 Go 工具链 / 原生 UI 联调时补验。

## 8. 个人版 vs 企业版对照（最终态）

| | 个人版 | 企业版 |
|---|---|---|
| 聊天 | 原生直连 :18789 | 原生直连 :18789 |
| 身份 | 写死 desktop-local/internal | 服务器登录发令牌 |
| 会话 | 不隔离 | 按 user_id 隔离 |
| 配置 | 本地改 | 本地改 + 服务器下发（含等级表） |
| 小窗 | F/O + 版本 | F/O + 等级 + 版本 + 用量 |
| 技能 | 先不用 | 以后补本地写文件 |
| 进程 | 8000 + 18789 | 8000 + 18789 + LLMGate服务器 |

## 9. 风险（就两个，都已有点解）

1. 对话泄露 → §3 会话隔离解决。
2. 技能装不了 → §5 本地写文件解决（往后放）。
3. 附带：OpenClaw 升级改工具名 → `protectedTools` 名单跟进，重跑插件测试（Step 7-⑤）。

## 11. 全面回归（2026-09-09，Step 6 完成后）

| 组 | 内容 | 结果 |
|---|---|---|
| A 8000 四阶段 | health/输入/身份回显/工具短路+串行/内容/输出/配置快照/审计/远端/runtime | 12/12 ✅（A6 曾用裸 tool 名踩 99 级零信任坑，改带 path 的 `write_file` 后过——证明零信任默认拦截在生效） |
| B LLMGate | health/登录/用户列表/建改删用户/非法等级回落/登录口径/终端/模型/用量 | 12/12 ✅（B2/B6/B8 挂 `FULLTEST_STRICT_IDENTITY` 开关：线上 exe 早于 011，字段级断言转 sqlite 覆盖 + 重启后严格验） |
| C 桌面静态 | 无 3000/18080 实调用/聊天区已删/legacy 开关×3 处/小窗 F+O/dist 新鲜 | 7/7 ✅ |
| D 身份语义 | 011 roundtrip/网关 1-4/users.txt 语义账号/判定/特例/插件数字 | 6/6 ✅ |
| E 插件 | `tsc` 零错 + 全套件 | 59/59 ✅ |
| F 桌面构建 | `vite build` | ✅ 2.35s |
| G 技能接口 | TestClient 进程内 9 项 | 9/9 ✅（线上旧进程 404，重启生效） |

遗留尾巴（非阻塞，上线前补）：①线上 `:8000`/`:8080` 是旧进程，Step 1/2/6 的改动需重启生效后重跑 B2/B6/B8 严格模式；
②`requireApproval` 原生 UI 渲染；③Go `go build` + 前端 `npm run build`；④`runtime/quarantine` 近永久隔离与 Step 4 会话隔离的叠加语义实测。

## 10. P1 口径（2026-09-09 定版：多用户自助砍，转正为"仅管理员"）

- 结论：控制台仅管理员可用；普通用户只做终端身份归属（`security_level/specials` 存库，
  经终端身份文件参与 access_control 判定），不开放控制台登录与自助接口。
- 已改（未编译，Go/Node 工具链上线前补验）：
  `README.md`（Key 管理改"管理员统一创建与分配" + 顶部口径声明）；
  `UsersView.vue`（角色改"管理员/终端用户（仅身份归属）" + 新增安全等级/特例列与表单）；
  `admin.ts` 的 `createUser` 加等级/特例参数；`LoginView.vue` 标题注明仅管理员可登录。
- 注意：`admin.ts/LoginView.vue` 的 diff 里大部分是别人已有的未提交改动（企业名、改密、终端 API 等），
  我只动了上面那几行，不要误 revert。
 
Step 8 restart plus strict re-verify, 2026-09-09 evening:
- Go: machine had none, MSI quiet install stuck on elevation, used portable zip Go 1.27.0 at E:/tiaozhanbei/MAC/.tools/go-tmp/go, kept for future builds.
- db.go: ExecWithRetry missed database/sql and time imports, added, go build ok to llmgate-new.exe 41MB, replaced llmgate.exe, old kept as llmgate-old.exe.
- 8080 new process applied 011_identity.sql, users has security_level and specials, 11 migrations recorded.
- B2 login JWT carries level, pass. B6 code one time reuse 401, pass. B8 key with usage deleted 200, pass. G online 5 of 5, pass. input allow plus exec block, pass.
- 8000 new live, 18789 new live, 18080 bridge stays down, legacy retired in Step 5.
- plugin tsc clean plus 59 of 59, vite build 2.46s ok.
- local state personal plus unbound, matches mini window, rebind with fresh code when needed.
