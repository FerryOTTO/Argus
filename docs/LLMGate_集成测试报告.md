# LLMGate × Argus 桌面端 集成测试报告

- **测试时间**：2026-09-09 03:00 – 03:45
- **被测范围**：LLMGate 服务端（Go/Gin，本次运行于 `http://127.0.0.1:8081`）+ Argus Python 后端（`http://127.0.0.1:8000`）+ argus-desktop Electron 桌面端
- **测试方法**：脚本化接口全量测试（含 mock 上游大模型服务、进程重启验证、边界/异常注入）+ 数据库直查取证 + 前端与构建产物校验
- **测试脚本**：`.tools\test_llmgate.py`（`setup` / `run` 两阶段）、`.tools\retest.py`（失败项复测）、结果明细 `.tools\test_results.json`
- **用例统计**：接口级用例 **76 项，通过 66，失败 10**；另有阶段一 2 项、边界/异常场景 12 项。
- **失败 10 项定性（经复测）**：

  | 类别 | 用例 | 说明 |
  |---|---|---|
  | 服务端真实缺陷（7） | C5、C6、C7、L8、F4、N2、M5 | 分别对应 BUG-04、BUG-05、BUG-02、BUG-01、BUG-10、BUG-06 |
  | 测试脚本自身问题（3，源于 2 处根因） | L2 | mock 上游的 SSE 使用了非法的 chunked 编码（未写分帧），修正分帧后流式转发 100% 正常 |
  | | I8、I9 | 用例把审计事件 `content` 传成了字符串；服务端期望对象，`REMOTE.md` 与 Argus `AuditEvent.content: Dict[str, Any]` 一致，服务端行为正确。改传对象后 accepted=1、重复上传 duplicates=1（幂等正常） |

  即：**7 项为服务端真实缺陷，3 项为测试脚本问题（L2 一处 + content 类型一处）**，修正脚本后该 3 项全部复测通过。

> 说明：LLMGate 配置为 8080，但 8080 被一个 CEF 远程调试进程占用，本次测试改用 8081；数据库中 `usage_records` 等关键表为直查取证。

---

## 一、缺陷总览

| 编号 | 严重级 | 标题 | 状态 |
|---|---|---|---|
| BUG-01 | **P0** | 用量统计与配额完全失效（`RecordUsage` 无调用点） | 确认 |
| BUG-02 | **P0** | Anthropic 类型提供商 100% 不可用（转换后 Content-Length 未更新，502） | 确认 |
| BUG-03 | **P0** | 新增模型/提供商必须重启进程才生效 | 确认 |
| BUG-04 | **P1** | 普通用户（role=user）无法登录控制台，多用户自助体系不可用 | 确认 |
| BUG-05 | **P1** | 用户自助接口 `/api/user/*` 全部 404，README 与实现不一致 | 确认 |
| BUG-06 | **P1** | Argus Python 侧企业同步链路完全未实现（`/v1/remote/*` 404） | 确认 |
| BUG-07 | P2 | 注册码可重复使用并轮换凭据，违反"一次性"安全约定 | 确认 |
| BUG-08 | P2 | 删除不存在的用户返回 500（应为 404） | 确认 |
| BUG-09 | P2 | 删除有历史会话日志的 API Key 返回 500（外键约束冲突） | 确认 |
| BUG-10 | P2 | `/favicon.ico` 404 | 确认 |
| BUG-11 | P2 | 会话列表空数据返回 `data:null` 而非空数组 | 确认 |
| BUG-12 | P2 | Python `enterprise_status()` 存在不可达死代码 | 确认 |
| BUG-13 | P2 | 部署约定冲突：端口 8080 被占、`bin/llmgate` 是 macOS 二进制、启动脚本未纳入 LLMGate | 确认 |
| BUG-14 | P2 | 安全配置沿用默认值（jwt_secret / encrypt_key 为空 / CORS 全开） | 确认 |

---

## 二、缺陷详情

### BUG-01（P0）用量统计与配额完全失效

**现象**
- 为用户 1 设置配额 `rpd=1` 后，连续发起 4 次 `/v1/chat/completions`，**全部返回 200**，没有任何一次被 429 拦截。
- `GET /api/admin/usage?user_id=1` 返回 `{"data":null}`。
- 直查 SQLite：`SELECT COUNT(*) FROM usage_records` → **0 条**（此前已完成十余次真实代理调用）。
- 仪表盘却有数据：`{"total_requests":801,"requests_today":801,"tokens_today":131}` —— 因为仪表盘读的是 `audit_logs`，与 `usage_records` 是两套数据。

**根因**
`service.QuotaService.RecordUsage()` 在全代码库中**只有定义、没有任何调用点**：

```
internal/service/quota_service.go:51   func (s *QuotaService) RecordUsage(...)
internal/store/quota_store.go:109      func (s *QuotaStore) RecordUsage(...)
（无第三处引用）
```

配额中间件 `internal/middleware/quota_check.go:61` 通过 `quotaStore.GetCurrentWindowUsage()` 统计 `usage_records` 来判定是否超限；既然这张表永远为空，`currentUsage` 恒为 0，**RPM/RPD/TPM/TPD 四类配额全部形同虚设**。

**影响**
- 配额/限流是 LLMGate 的核心卖点之一，当前完全不生效，任意用户可无限调用。
- 用量统计页面、按量计费/对账数据全部为空。
- 仪表盘的 token 数与用量接口口径不一致，会造成"有请求但没用量"的困惑。

**复现**
```
POST /api/admin/quotas  {"user_id":1,"model_id":"<model>","quota_type":"rpd","limit_value":1}
POST /v1/chat/completions × 4（带 admin JWT）  → 200,200,200,200（应为首次 200，之后 429）
GET  /api/admin/usage?user_id=1                → {"data":null}
```

**修复建议**
在代理成功后调用用量落库：在 `internal/proxy/handler.go` 的 `proxyRequest` 末尾（或审计中间件 `internal/middleware/audit_log.go` 的响应后处理中），取出 `prompt_tokens` / `completion_tokens` / `status_code` / `api_key_id` / `user_id`，调用 `quotaService.RecordUsage(...)`。注意 `QuotaCheck` 中间件目前只持有 `quotaService` 里的 `quotaStore`，需要把 `RecordUsage` 的能力暴露到同一条链路上。

---

### BUG-02（P0）Anthropic 类型提供商 100% 不可用

**现象**
向 `provider_type=anthropic` 的提供商发起请求，网关返回 502，且**上游根本没收到请求**：

```json
{"error":{"message":"Failed to connect to upstream provider \"qa-prov-f6cb03-2\": http: ContentLength=121 with Body length 130","type":"upstream_error","code":"bad_gateway"}}
```

**根因**
`internal/proxy/handler.go`:
- 第 135–143 行：Anthropic 请求体被 `ConvertAnthropicRequest()` 转换后赋值给局部变量 `body`；
- 第 173 行：`c.Request.Body = io.NopCloser(bytes.NewReader(body))` **只替换了 Body，没有同步更新 `c.Request.ContentLength`**（仍为原始请求长度 121，新 body 为 130）；
- 非流式分支走 `httputil.ReverseProxy`，Go 的 transport 发现实际写出字节数与声明的 `Content-Length` 不一致，直接报 `ContentLength=121 with Body length 130` 并中断。

**影响**
所有 Anthropic 类型的提供商（包括 Claude 系）在网关层完全不可用；README 宣称的"Anthropic 转换"功能实际不可用。

**复现**
```
1) 创建 provider：provider_type=anthropic, api_base_url=http://127.0.0.1:8899
2) 创建模型 anth-mock 并（重启后）确保进入路由表
3) POST /v1/chat/completions {"model":"anth-mock","system":"you are a bot","max_tokens":64,"messages":[{"role":"user","content":"hi"}]}
   → 502 upstream_error
```

**修复建议**
替换 Body 时同步设置长度：
```go
c.Request.Body = io.NopCloser(bytes.NewReader(body))
c.Request.ContentLength = int64(len(body))
c.Request.Header.Set("Content-Length", strconv.FormatInt(c.Request.ContentLength, 10))
```
另外补充一个 Anthropic 格式的端到端用例（当前 `e2e_telemetry_test.sh` 未覆盖 Anthropic 转换）。

---

### BUG-03（P0）新增模型/提供商必须重启进程才生效

**现象**
- 创建提供商 + 模型成功后，立即 `GET /v1/models` 返回 `{"object":"list","data":[]}`，`GET /api/admin/models` 同样为空列表；
- 重启进程后，日志出现 `INFO loaded model routing table model_count=N`，此时 `/v1/models` 才出现新模型；
- 用新模型调用 `/v1/chat/completions` → 404（模型未进入路由表）。

**根因**
`internal/proxy/provider_router.go` 的注释写明 `LoadModels` 应"在 providers/models 变更时调用"，但全库仅在 `cmd/server/main.go:85` 启动时调用一次；`CreateProvider` / `CreateModel` / `DeleteModel` / `UpdateProvider` 均未触发重新加载。

**影响**
管理员在控制台新增模型后看不到、也用不了，必须重启服务；对"网关"类产品的可用性影响很大（每次改配置都要停服）。

**复现**
```
POST /api/admin/providers {name:..., provider_type:"openai", api_base_url:..., api_key:...}  → 201
POST /api/admin/models {provider_id:X, model_id:"qa-gpt-xxxx"}                              → 201
GET  /v1/models                                                                              → data:[]   ✗
（重启进程）
GET  /v1/models                                                                              → data:[...] ✓
```

**修复建议**
在 `AdminProviderHandler` 的 Create/Update/Delete（provider 与 model）成功后调用 `proxyRouter.LoadModels()`；可通过给 handler 注入一个 `reload func() error` 回调，或在 store 层加变更通知。

---

### BUG-04（P1）普通用户无法登录控制台

**现象**
管理员创建 `role=user` 的账号后，用该账号登录返回 403：

```json
{"error":{"code":"admin_only","message":"admin only: regular users cannot sign in to the console","type":"authentication_error"}}
```

**根因**
`internal/handler/auth_handler.go` 的 Login 中对非 admin 角色直接拒绝（错误码 `admin_only`）。配合 BUG-05 可见：**普通用户自助体系已被整体移除**。

**影响**
- README 描述的"用户自助创建 API Key、查看个人用量"能力不存在；
- 管理端"用户管理"可以建普通用户，但这些账号没有任何用途（建了也登不进来），属于明显的半成品；
- 若产品定位是"企业网关 + 多用户"，这是功能缺失；若定位是"仅管理员"，则用户管理和 README 需要同步调整。

**复现**
```
POST /api/admin/users {username:"tester_x", password:"...", role:"user"}  → 201
POST /api/auth/login  {username:"tester_x", password:"..."}              → 403 admin_only
```

---

### BUG-05（P1）用户自助接口全部 404，文档与实现不一致

**现象**
```
GET /api/user/api-keys  → 404
GET /api/user/usage     → 404
```

**根因**
`internal/handler/router.go` 中不存在 `/api/user` 路由组；对应的 `user_apikey.go` / `user_password.go` / `user_usage.go` 已被删除（git status 显示为 D）。前端 `web/src/router/index.ts` 也只有 `/login` 与 `/admin/*`，无用户自助页面。

**影响**
README 第 109–115 行仍列出 `/api/user/api-keys`、`/api/user/usage` 等接口，文档与实现严重不一致，会误导后续对接方。

**修复建议**
二选一：① 恢复用户自助功能（配合 BUG-04 放开登录）；② 从 README 与用户管理页面中移除相关描述，并隐藏"创建普通用户"入口。

---

### BUG-06（P1）Argus Python 侧企业同步链路完全未实现

**现象**
桌面端 `src/renderer/components/EnterpriseMini.vue` 第 29 行调用：

```js
fetch("http://127.0.0.1:8000/v1/remote/status")
```

实测返回 **404**。进一步核查 Python 侧：

| 检查项 | 结果 |
|---|---|
| `GET /v1/remote/status` | **404**（路由不存在） |
| `POST /v1/remote/register`、`/sync-config`、`/unbind` | **全部不存在** |
| `argus/remote/` 包（client / store / config_apply / counters / audit_tail / scheduler） | **目录不存在** |
| `configs/remote.json`（token、terminal_id、llm 凭据） | **文件不存在** |
| `runtime/remote/cursors.json`（上报游标） | **文件不存在** |

**根因**
`Argus/docs/LLMGate对接方案.md` 的 P0–P3 阶段（注册与安全存储、心跳+配置同步、report+审计上传、企业版 UI）**尚未开工**，仅完成了"本地模块配置读写"（`argus/api/local_config_routes.py`）和 `enterprise_status()` 这个只读占位接口。

**影响**
- **合并链路实际是断的**：LLMGate 服务端六个遥测接口全部就绪（本次测试 13 项遥测用例全通过），但没有任何客户端会去调用它们。管理台永远不会出现真实的在线终端。
- 桌面端"企业面板"的第二个 fetch 被 `.catch(()=>null)` 静默吞掉，界面上看不出异常 —— 属于**静默失败**，用户会误以为已接入。
- `enterprise_status()` 返回的 `bound` 恒为 false、`base_url` 恒为空。

**复现**
```
GET http://127.0.0.1:8000/v1/remote/status   → 404 Not Found
打开桌面端企业面板                            → 无报错，但企业信息始终为空
```

**修复建议**
按对接方案第 4 章补齐 `argus/remote/` 六个模块与四个 `/v1/remote/*` 接口；前端至少在 fetch 失败时给出"未接入企业版"的显式提示，不要静默吞异常。

---

### BUG-07（P2）注册码可重复使用并轮换凭据

**现象**
同一个 `registration_code` 连续调用两次 `/telemetry/v1/register`，**两次都返回 200**，并重新签发 token 与 LLM 凭据（`sk-...`），第二次返回后旧 token 立即失效。

**期望**
`对接方案` 第 10 章安全红线第 2 条："注册码一次性，用完内存+落盘清除；重复注册会轮换旧凭据，需二次确认"。当前实现没有"用完即清"，任何拿到旧码的人都可以重新注册并**踢掉已在线的终端**。

**影响**
注册码一旦泄漏（日志、截图、聊天记录），攻击者可反复注册，造成终端被顶替、LLM 凭据被替换。

**修复建议**
注册成功后将 `registration_code` 置空/标记已用；确需轮换时要求管理员重新生成（`regenerate-code` 接口已存在）。

---

### BUG-08（P2）删除不存在的用户返回 500

```
DELETE /api/admin/users/99999 → 500 {"error":{"message":"failed to delete user","type":"internal_error"}}
```
对比：更新不存在的终端返回 404（`terminal not found`），行为不一致。建议对"资源不存在"统一返回 404。

---

### BUG-09（P2）删除有历史会话日志的 API Key 返回 500

**现象**
```
DELETE /api/admin/api-keys/17   → 200 {"message":"api key deleted"}     （该 key 无会话日志）
新建 key 后立即删除              → 200                                   （无会话日志）
DELETE /api/admin/api-keys/15   → 500 {"error":{"message":"failed to delete api key","type":"internal_error"}}
                                       （该 key 有 3 条 conversation_logs）
```

**根因**
`conversation_logs.api_key_id` 是指向 `api_keys(id)` 的外键，建表语句未加 `ON DELETE CASCADE`，删除接口也没有先清理关联日志。只要该 Key 产生过会话记录，删除就必然触发外键约束失败，落到 `internal_error` 500 分支（且错误细节只进了日志，未返回给调用方）。

**影响**
控制台"删除 API Key"按钮对用过的 Key 直接报错 500，管理员无法清理失效凭据，只能停服手工改库。

**修复建议**
迁移脚本为 `conversation_logs.api_key_id` 增加 `ON DELETE CASCADE`（或在删除前 `UPDATE conversation_logs SET api_key_id=NULL WHERE api_key_id=?`）；同时把外键冲突识别为 409 并给出明确提示，而不是笼统 500。

---

### BUG-10（P2）`/favicon.ico` 404

`GET /favicon.ico` → `404 page not found`。`web/dist` 下只有 `assets/`、`index.html`、`vite.svg`，缺少 `favicon.ico`，而 `internal/static` 已注册该路由。浏览器控制台会持续报 404，属观感问题。

---

### BUG-11（P2）会话列表空数据返回 `data:null`

```
GET /api/admin/conversations → {"data":null,"page":1,"page_size":20,"total":0}
```
有数据时 `data` 为数组，无数据时为 `null`，前端需要额外判空，容易触发 `data.length` 报错。建议统一返回 `[]`。

---

### BUG-12（P2）Python `enterprise_status()` 死代码

`Argus/argus/api/local_config_routes.py` 第 204 行 `return` 之后，第 205–207 行仍有一段重复的 `remote = _read_json(...)` / `bound = ...` / `tok = ...` 逻辑，**永远不可达**。应为重构残留，需清理（后续若要补 `/v1/remote/status`，正好在此实现）。

---

### BUG-13（P2）部署约定冲突与环境问题

| 问题 | 说明 |
|---|---|
| 端口冲突 | `对接方案` 与 `REMOTE.md` 约定 LLMGate 在 **8080**，但本机 8080 长期被一个 CEF 远程调试进程占用（返回 `CEF remote debugging` 页面）。按默认配置启动会直接 `bind: address already in use`。 |
| 二进制不可用 | 仓库中的 `bin/llmgate` 是 **macOS Mach-O**（文件头 `cf fa ed fe`），在 Windows 上无法执行；`Makefile` 的 `build` 目标输出的 `bin/llmgate.exe` 路径与实际启动脚本也不一致。本次测试是用 `go build -o llmgate.exe ./cmd/server/` 现场编译的。 |
| 启动脚本未包含 LLMGate | `scripts/Start-ArgusDesktop.ps1` 只启动 FastAPI(8000)、OpenClaw(18789)、Bridge(18080)、OpenGuard(3000)，**没有启动 LLMGate**；`src/main/daemon.js` 的 `startAll()` 同样未纳入。也就是说合并后桌面端启动时不会拉起网关。 |

---

### BUG-14（P2）安全配置沿用默认值

`configs/config.yaml`：
```yaml
server:
  jwt_secret: "change-me-in-production"   # 未改
  cors_origins: ["*"]                     # 全开
security:
  encrypt_key: ""                         # 为空
```
- `encrypt_key` 为空时启动日志明确告警：`WARN Provider API keys will be stored in plaintext`，**所有上游大模型 API Key 明文入库**；
- 默认 JWT 密钥可伪造任意管理员 token；
- CORS 全开。

（对接方案第 10 章安全红线第 5 条已列出这几项，属"上线前必改"。）

---

## 三、已通过的功能（抽样）

| 模块 | 用例 | 结果 |
|---|---|---|
| 基础 | `/health`、安全响应头（X-Content-Type-Options / X-Frame-Options / Referrer-Policy）、CORS 头与 OPTIONS 预检 204 | ✅ 4/4 |
| 认证 | 管理员登录、错误密码 401、缺字段 400、refresh、`/api/auth/info`、SSO 列表 | ✅ 6/6 |
| 权限 | 无令牌 401；普通用户访问管理接口 403 | ✅ |
| 用户管理 | 创建 / 列表 / 更新 / 重置密码（重置后旧密码 401、新密码可用） | ✅ 4/5（登录见 BUG-04） |
| 提供商与模型 | 创建 / 列表 / 更新，模型映射创建 | ✅ 4/4（生效时机见 BUG-03） |
| API Key | 创建返回明文、列表不回显明文、更新名称与白名单 | ✅ 3/3 |
| 网关鉴权 | Key 白名单内放行、白名单外 403、未知模型 404、无鉴权 401 | ✅ 4/4 |
| 网关代理 | 非流式转发、流式 SSE（`data:` 分块正确）、`/v1/completions`、`api_base_url` 带 `/v1` 时路径拼接正确、上游 Authorization 注入 | ✅ 5/6（Anthropic 见 BUG-02） |
| 会话日志 | 代理请求落库、详情可读 | ✅ 2/2 |
| 终端管理 | 创建（返回注册码）、列表、读取配置、下发配置、更新、重新生成注册码、吊销 | ✅ 7/7 |
| 遥测全链路 | 注册码换 token（含 `llm.base_url`）、错误码 401、心跳 `config_pending=true`、拉配置版本、回执超前 409、正常回执、增量上报、审计事件上传 **accepted=1**、重复上传 **duplicates=1（幂等）**、非法 action 整批 400、无令牌 401、吊销后令牌失效 401、`agent_type` 不匹配 409、单批 500 通过 / 501 拒绝 | ✅ 全通过 |
| 终端聚合 | `token_usage_total=12500`、`alert_count_total=2`、`config_applied_version=1`、`online=true` 正确回填 | ✅ |
| 审计与仪表盘 | 审计日志列表与导出、仪表盘统计、终端审计列表/统计/按终端聚合/导出 | ✅ 7/7 |
| 系统设置 | GET / PUT（含 enterprise_name、system_base_url、open_models、llm_base_url） | ✅ 2/2 |
| LLMGate 前端 | SPA 首页、JS/CSS/vite.svg 资源全部 200 | ✅ |
| Argus 8000 | `/health`、`GET`/`PUT /v1/local/config`、`/v1/local/enterprise/status`、`/v1/desktop/runtime`、`/v1/audit/overview` | ✅ 6/7（`/v1/remote/status` 见 BUG-06） |
| Electron 桌面端 | `vite build` 成功（1591 modules，11.28s）、打包产物 `Argus.exe`（177MB）存在、5 个内嵌 iframe 监控页与 OpenGuard 登录页均 200 | ✅ |

---

## 四、未覆盖 / 遗留

1. **全局速率限制**（`/v1` 组 120 次/分钟）未做压测验证。
2. **SSO/OAuth 真实登录流程**（OIDC / OAuth2 回调）未接真实 IdP，仅验证了配置接口与列表接口。
3. **Electron 应用 UI 交互**（点击各监控页、企业面板的实际渲染）未做浏览器自动化点击，只验证了构建产物与内嵌页可达性。
4. **断网 / 服务端重启后的客户端重连退避**：因客户端同步器未实现（BUG-06），该场景无法测试。
5. **并发上报与大数据量**：仅验证了单批 500/501 边界，未做多终端并发。

---

## 五、处理优先级建议

1. **先修 P0**：BUG-01（用量落库，牵动配额与统计）、BUG-02（Anthropic 一行修复）、BUG-03（模型热加载）。这三项直接决定核心功能是否可用。
2. **再定产品口径**：BUG-04 / BUG-05 需要明确"是否保留多用户自助"，据此改代码或改文档。
3. **补客户端**：BUG-06 是合并的真正缺口 —— 服务端已就绪，客户端同步器一行未写，需按对接方案 P0→P3 补齐。
4. **上线前**：BUG-14（密钥与加密）、BUG-13（端口、启动脚本纳入 LLMGate、Windows 构建）、BUG-09（API Key 删除外键）。

---

## 附录：复现与环境

- 启动 LLMGate（本测试）：`cd LLMGate && llmgate.exe -config <config>`（必须用仓库根目录为工作目录，`migrations/` 与 `web/dist` 为相对路径）
- 默认管理员：`admin` / `admin123`
- 测试脚本：`.tools\test_llmgate.py`（`setup` 阶段建数据 → 重启服务 → `run` 阶段跑全量）、`.tools\retest.py`（单项复测）
- 明细结果：`.tools\test_results.json`（含每个用例的方法、URL、状态码、响应片段）
- mock 上游大模型：`test_llmgate.py` 内置，监听 `127.0.0.1:8899`，支持 `/v1/models`、chat/completions（非流式 + SSE 流式）、completions，可记录上游收到的请求体用于校验协议转换
- **测试残留数据（未清理）**：受 BUG-09 影响，3 个产生过会话日志的测试 API Key（id 15 / 16 / 18，名称 `e2e-renamed`、`wild-f6cb03`、`retest-a758`）无法通过接口删除，仍留在 `api_keys` 表中；其余 provider / model / user / terminal / quota 测试数据均已清理。需要彻底清库时可停服后执行 `DELETE FROM conversation_logs WHERE api_key_id IN (15,16,18)` 再删 Key，或直接重置 `data/llmgate.db`。
