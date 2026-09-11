# LLMGate × Clawguard 修复复审报告（第二轮）

- **复审时间**：2026-09-09 10:00 – 10:40
- **复审方式**：从当前源码重新编译 `llmgate.exe`（09:59 构建）→ 8080 端口重启 → 36 项回归用例（`.tools\verify_fixed.py`）+ 3 个精确定位脚本（`verify2.py` / `verify3_fk.py`）+ 服务端日志取证
- **对照基线**：第一轮报告 `LLMGate_集成测试报告.md` 的 14 个缺陷
- **结果总览**：**6 项修复确认有效（含全部 3 个 P0），2 项按设计关闭，1 项部分修复，1 项未修复；另发现 1 个修复引入的回归和 1 个此前未暴露的并发缺陷**

| 编号 | 原级别 | 结论 | 说明 |
|---|---|---|---|
| BUG-01 | P0 | ✅ **已修复** | 用量落库 + 配额拦截均验证通过 |
| BUG-02 | P0 | ✅ **已修复** | Anthropic 转发 200，上游收到 system 角色 |
| BUG-03 | P0 | ✅ **已修复** | 新增模型即时生效，无需重启 |
| BUG-04 | P1 | 🔵 **按设计关闭** | README 明确"用户自助已下线"，控制台仅管理员 |
| BUG-05 | P1 | 🔵 **按设计关闭** | 同上，接口随功能移除，文档已同步 |
| BUG-06 | P1 | 🟡 **部分修复** | status/bind/unbind 已有；心跳循环等同步器仍缺 |
| BUG-07 | P2 | ❌ **未修复** | 注册码仍可重复使用并轮换凭据 |
| BUG-08 | P2 | ✅ **已修复** | 删除不存在用户返回 404 |
| BUG-09 | P2 | ❌ **未修复（根因转移）** | 见 NEW-1，FK 冲突从 conversation_logs 转移到 usage_records |
| BUG-10 | P2 | ✅ **已修复** | favicon 回退 vite.svg，200 |
| BUG-11 | P2 | ✅ **已修复** | conversations 空数据返回 `[]` |
| BUG-12 | P2 | ⚪ 未处理 | 8080 冲突已自行消失；启动脚本仍未纳入 LLMGate；bin/llmgate 仍是 macOS 二进制 |
| BUG-13 | P2 | ⚪ 未处理 | 安全配置仍为默认值 |
| NEW-1 | **P1** | 🆕 新发现 | 删除有用量记录的 API Key 500（修复 BUG-01 后引入的新 FK 路径） |
| NEW-2 | **P1** | 🆕 新发现 | 并发写下大量 `SQLITE_BUSY` → 500 + 审计日志丢失 |

---

## 一、修复确认（6 项，含全部 P0）

### BUG-01 用量与配额 —— ✅ 修复
- `internal/proxy/handler.go:301` 已调用 `quotaService.RecordUsage(...)`（新增调用点，签名改为可空指针以兼容 JWT 调用）；
- `internal/middleware/quota_check.go` 超限时补了 `c.Abort()`；
- 新增迁移 `010_usage_nullable.sql` 重建 `usage_records` / `conversation_logs`（api_key_id、user_id 可空）。
- **实测**：配额 `rpd=1` 下三次请求状态码 `[200, 429, 429]`；`usage_records` 落库；`GET /api/admin/usage?user_id=1` 返回真实数据（prompt_tokens/completion_tokens/latency_ms 齐全）。

### BUG-02 Anthropic 转换 —— ✅ 修复
- `proxy/handler.go:176-179` 转换后同步了 `c.Request.ContentLength`；
- **实测**：Anthropic 风格请求 → 200，mock 上游收到 `roles=['system', 'user']`（转换正确）。

### BUG-03 模型热加载 —— ✅ 修复
- `main.go:114-118` 构造 `reloadModels` 回调注入 router，`AdminProviderHandler.OnChange` 在 provider/model 增删改后触发 `LoadModels()`；
- **实测**：创建提供商+模型后**不重启**，`/v1/models` 与 `/api/admin/models` 立即可见，且可直接调用网关。

### BUG-08 / BUG-10 / BUG-11 —— ✅ 修复
- 删除不存在用户 → `404 user not found`；
- `/favicon.ico` → 200（dist 无文件时回退 `vite.svg`）；
- `/api/admin/conversations` 空数据 → 返回数组而非 `null`。

---

## 二、按设计关闭（2 项）

BUG-04 / BUG-05：README 第 109 行起已明确——

> 用户自助（已下线）：历史版本曾提供 `/api/user/api-keys` 与 `/api/user/usage` 及对应前端页面，现已整体移除：控制台仅管理员可登录（非 admin 返回 403 admin_only）。

文档与实现已一致，接受该口径。**遗留一个小问题**：管理端"用户管理"仍可创建 `role=user` 的账号，但这些账号无法登录也无自助入口，属于无用数据入口，建议前端隐藏该角色或加提示。

---

## 三、部分修复（1 项）：BUG-06 客户端同步器

**已完成**：`ClawguardV2.1/clawguard/api/remote_routes.py`（新增）提供 `GET /v1/remote/status`、`POST /v1/remote/bind`、`DELETE /v1/remote/unbind`，桌面端 `EnterpriseMini.vue` 依赖的 status 接口不再 404。

**仍缺失（这是当前唯一挡住"管理台看到真实终端在线"的问题）**：
1. 没有**按注册码注册**的接口（只有手工 bind token），与 LLMGate 的 `POST /telemetry/v1/register` 流程未打通；
2. 没有**心跳 / 配置拉取 / 回执 / report / audit events** 的任何调度器实现（对接方案 P1/P2 阶段内容）；
3. `clawguard/remote/` 包（client / counters / audit_tail / scheduler）仍不存在，`runtime/remote/cursors.json` 不存在。

**实证**：管理台出现了一台真实终端 `clawguard-home-01`（hostname=home-desktop，clawguard_version=2.1），10:14:15 完成注册（status=active）——说明注册动作已经跑通过一次；但 `last_seen_at` 停在 10:14:15，30 分钟后 `online=false`，`token_usage_total=0`、`config_version=0`、终端审计事件为空。**注册了、然后没有心跳** —— 客户端缺的正是那个循环。

---

## 四、未修复（1 项）：BUG-07 注册码可重复使用

实测（独立终端）：同一 `registration_code` 首次注册 200，**复用仍 200** 并重新签发 token 与 LLM key，复用后旧 token 立即 401（凭据被轮换）。DB 中 `registration_code_hash` 注册后仍为 64 字符（未清除）。

原报告的分析与风险不变：注册码泄漏后可反复注册顶替在线终端。建议注册成功后将码置空/作废，轮换走既有的 `regenerate-code` 接口。

---

## 五、新发现（2 项，均为 P1）

### NEW-1 删除有用量记录的 API Key 仍然 500 —— FK 根因转移

这是 **BUG-01 修复引入的回归**：
- 之前用量表恒空，所以 `usage_records.api_key_id → api_keys(id)` 外键从不触发；
- 现在用量落库生效，`apikey_store.Delete()` 只解绑了 `conversation_logs`，**没有解绑 `usage_records`**。

**实证**（`verify3_fk.py`）：
```
key 有 1 条 conversation_logs + 1 条 usage_records
DELETE /api/admin/api-keys/:id  → 500 failed to delete api key
服务端日志: constraint failed: FOREIGN KEY constraint failed (787)
手动 UPDATE usage_records SET api_key_id=NULL WHERE api_key_id=? 后
DELETE → 200 api key deleted
```

**修复建议**：`Delete()` 中在删除前追加一句
`UPDATE usage_records SET api_key_id = NULL WHERE api_key_id = ?`
（migration 010 已把该列改为 nullable，条件已具备）。注意 `ConversationHandler` / 仪表盘如果按 api_key_id 关联统计，需要决定置空后的展示口径。

### NEW-2 并发写下大量 SQLITE_BUSY：500 + 审计日志丢失

服务端日志（本次运行 10:00–10:14）捕获数十条：

```
ERROR failed to insert audit log error="database is locked (5) (SQLITE_BUSY)"
  → 10:03:20 一秒内出现 15 条（覆盖 auth / admin_provider / chat_completion 等多种 action）
ERROR failed to delete user error="failed to delete user: database is locked (5) (SQLITE_BUSY)"   × 10+
ERROR failed to delete provider / terminal / api key / quota / model ... SQLITE_BUSY
ERROR failed to create api key ... SQLITE_BUSY
```

**根因**：`internal/store/db.go:38` 用 `db.Exec("PRAGMA busy_timeout=5000")` 设置超时，但 **busy_timeout 是 per-connection 的 PRAGMA**——它只作用于执行它的那一条池化连接，连接池里后续新建的连接全部没有生效；同时没有 `SetMaxOpenConns(1)`。多连接并发写时，等待时间为 0，直接 SQLITE_BUSY。

**表现**：连续批量管理操作（连续删除/创建）时约 50% 请求 500，**重复执行又能成功**（非确定性），极易被当成"偶发抽风"忽略。更严重的是**审计日志插入失败 = 审计数据静默丢失**，对一个安全审计产品是硬伤。

**修复建议（任选其一，推荐 1+2 组合）**：
1. `db.SetMaxOpenConns(1)`——SQLite 单写者模型下最简单可靠；
2. 把 PRAGMA 放进 DSN，让每个新连接自动生效（modernc 驱动语法）：
   `sqlx.Open("sqlite", "file:data/llmgate.db?_pragma=busy_timeout(5000)&_pragma=journal_mode(WAL)&_pragma=foreign_keys(1)")`
3. 对 SQLITE_BUSY 做带退避的重试。

---

## 六、遗留未动（原 BUG-12/13/14）

| 项 | 现状 |
|---|---|
| 8080 端口 | ✅ 冲突已消失（原 CEF 调试进程不在了），LLMGate 已按默认配置跑在 8080 |
| 启动脚本 | ❌ `Start-ClawguardDesktop.ps1` 与 `src/main/daemon.js` 仍不启动 LLMGate |
| `bin/llmgate` | ❌ 仍是 macOS Mach-O（`cf fa ed fe`），Windows 不可用 |
| 安全配置 | ❌ `jwt_secret: change-me-in-production`、`encrypt_key: ""`（provider key 明文入库，启动日志仍 WARN）、CORS `*` |

---

## 七、观察项（待确认，未定级）

**跨进程 WAL 可见性异常**：复审中发现，API 删除资源返回 200 且 API 自身查询已不可见，但**用外部进程直读 `data/llmgate.db`（Python sqlite3）仍能看到已删除的行**；反之，外部进程直接 UPDATE 的数据，API 也感知不到。API 自身闭环（create → list → delete → list）完全一致。

初步判断：这是 Go `modernc.org/sqlite` 与外部 SQLite 读者之间 **WAL/-shm 跨进程互操作**问题，而非应用逻辑缺陷——但有一个实际影响：**服务运行期间用外部工具直接读/备份 `data/llmgate.db` 可能拿到旧快照**。建议：
1. 用官方 `sqlite3` CLI 复核一次，确认是否同样现象；
2. 备份改走 `VACUUM INTO` 或停服备份，避免"备份了旧数据"；
3. 如确认是驱动层问题，考虑切换 `mattn/go-sqlite3`（cgo）或升级 modernc 版本。

---

## 八、遗留测试数据

- `users` 表残留测试账号：`tester_*`（4 个）、`probe_u`、`pwtest`、`rgu_*`（4 个）——清理时遇到 NEW-2 的 BUSY 500，**重试即可删除**；
- `api_keys` 表残留约 20 个"终端 LLM 凭据 - xxx"测试 Key；
- `clawguard-home-01`、`dev-test-01`、`e2e-audit-t1` 是真实/原有终端，未动。

## 九、建议的下一步（按优先级）

1. **NEW-2（SQLITE_BUSY）**：一行 `SetMaxOpenConns(1)` + DSN PRAGMA，性价比最高，同时消除批量操作 500 和审计日志丢失；
2. **NEW-1（usage_records FK）**：`Delete()` 加一句解绑；
3. **BUG-06 收尾**：把 `remote_routes.py` 从"本地文件记录"升级为真同步器——register(注册码) → 心跳循环(45s) → 配置拉取/回执 → report/audit 上报（对接方案 P1/P2）；否则 `clawguard-home-01` 永远离线；
4. **BUG-07**：注册码一次性作废；
5. 部署三件套：启动脚本纳入 LLMGate、换 `bin/llmgate` 为 Windows 构建、改默认密钥。

---

## 十、复审后追加验证（10:45 复跑，针对新实例）

第一轮复审提交后，你在继续修改，我用同一套回归脚本在新实例（PID 48540）上复跑，结论有更新：

| 缺陷 | 上一轮结论 | 最新结论 |
|---|---|---|
| BUG-07 注册码一次性 | ❌ 未修复 | ✅ **已修复** —— 首次 200，复用返回 `401 invalid_registration_code` |
| BUG-09 删除有用量记录的 Key | ❌ 未修复 | ✅ **已修复** —— 返回 `200 api key deleted`（`usage_records` 已解绑） |
| BUG-06 客户端注册 | 🟡 无 register 接口 | 🟡 **新增 `POST /v1/remote/register`**（真实调用 LLMGate `/telemetry/v1/register` 并把 token 写入 `configs/remote.json`），但**心跳/上报/审计上传仍无** |
| NEW-1 / NEW-2 | P1 新发现 | NEW-1 已随 BUG-09 一并解决；**NEW-2（SQLITE_BUSY）未确认是否处理** |

回归结果：**32/36 通过**（4 项未过中，BUG-04/05 为按设计关闭，TL-9 为脚本取值问题、单独直查聚合正常）。

**仍待落实的两点**：

1. **无心跳循环 → 终端仍会离线**。`remote_routes.py` 里没有 heartbeat / report / audit events / 配置拉取的任何实现。你新加的 register 能把终端注册成 active，但管理台判定在线依赖 120s 内的心跳，没有循环就一定会掉线（上一轮 `clawguard-home-01` 已验证过这个现象）。
2. **`agent_type` 默认值不匹配（待验证）**。`RegisterBody.agent_type` 默认是 `"clawguard"`，而 LLMGate 建终端时是 `"openclaw"`，两者不一致会触发 `409 agent_type mismatch`。如果调用方不显式传 `agent_type=openclaw`，注册会失败。**本项尚未实测**（见下）。

**一个阻塞项**：复跑到 10:45 之后，`admin / admin123` 登录开始返回 401（同一次运行中前几分钟还正常），推测你刚改了管理员密码或轮换 `jwt_secret`（对应 BUG-13 安全加固）。最后的 register 端到端脚本因此没能跑完。请告知新的管理员凭据，或确认是否已改密——我把 register 链路（含 agent_type 那项）补测完。

---

*附件：`.tools\verify_fixed.py`（回归套件）、`.tools\verify2.py` / `.tools\verify3_fk.py`（根因定位）、`.tools\verify4_register.py`（register 端到端）、`.tools\verify_results.json`（明细）、`.tools\cleanup2.py`（数据清理）*
