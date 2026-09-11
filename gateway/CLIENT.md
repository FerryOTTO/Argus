# 扩展治理：客户端（终端侧）对接规范（CLIENT）

> **读者**：Clawguard 客户端工程师（在终端侧实现“安装前审批 + Skill 分发接收”
> 能力的适配者）。
> **配套文档**：[REMOTE.md](./REMOTE.md) 是遥测/集控基础协议（注册、心跳、配置
> 下发、上报）；本文只描述**扩展治理**两件事的客户端行为与契约：
>
> 1. **安装审批** —— 智能体安装新 Skill / 接入新 MCP 前须上报申请，管理员放行后才允许安装；
> 2. **Skill 分发** —— 管理员把 Skill 压缩包分发给目标终端（或配置新终端默认包），
>    客户端负责拉取、校验安装并回执。
>
> Skill 压缩包的制作规范（zip 布局、SKILL.md frontmatter、限制）见
> [SKILL_CREATION.md](./SKILL_CREATION.md)。

---

## 1. 角色与总体时序

```
┌────────────────────────┐        ┌──────────────────────────┐
│  终端（客户端实现方）    │        │  LLMGate（集控/管理端）    │
└───────────┬────────────┘        └────────────┬─────────────┘
            │                                  │
  ════ A. Skill/MCP 安装审批 ═════            │
            │  ① 即将安装 skill/接入 mcp：      │
            │     POST /extensions/requests    │  创建审批单（state=pending）
            │  ───────────────────────────────▶│  返回 {request_id, state}
            │                                  │
            │  ② 轮询审批结果（建议 30s/次）     │  管理员审批：
            │     GET /extensions/requests     │  approved（放行）/ rejected（驳回+理由）
            │  ◀───────────────────────────────│
            │  ③ state=approved → 执行安装      │
            │     state=rejected → 禁止安装，   │
            │     展示 review_note（驳回理由）   │
            │                                  │
  ════ B. Skill 分发 ══════════════           │
            │  ④ 注册/心跳响应 skills_pending   │  （管理员已配置默认包/分发）
            │  ◀───────────────────────────────│
            │  ⑤ GET /extensions/skills        │  返回分配的包（zip+版本）
            │  ◀───────────────────────────────│
            │  ⑥ 解压 → 校验 → 安装             │
            │  ⑦ POST /extensions/skills/applied（回执 ok/failed）
            │  ───────────────────────────────▶│
```

> 完整路径前缀 `/telemetry/v1`（与 REMOTE.md 一致），鉴权同为
> `Authorization: Bearer <telemetry token>`。所有时间字段 ISO 8601 UTC。

---

## 2. 安装审批（skill / mcp）

### 2.1 触发时机（客户端必须遵守）

在**执行安装动作之前**上报申请；未获 `approved` 前不得安装。典型触发点：

| 场景 | kind | 说明 |
|------|------|------|
| 智能体（OpenClaw 等）要安装一个未在本地的 skill | `skill` | 含“从市场/仓库安装、手工放置后自动发现”等一切将引入新 skill 的路径 |
| 要接入一个新的 MCP server（含本地进程式、远程 SSE/HTTP、stdio 启停） | `mcp` | “接入”= 会实际启动/连接该 server 并暴露其工具给智能体 |

已安装/已接入项的重启、配置微调**不需要**申请；只有“新增”需要。若本地已有同名
skill/server（版本覆盖、重连同一 server），视为存量维护，不在审批范围。

### 2.2 上报申请

`POST /telemetry/v1/extensions/requests`

```json
{
  "kind": "skill",
  "name": "pdf-briefing",
  "source": "https://skills.example.com/pdf-briefing",
  "payload": {
    "summary": "将 PDF 文档转成结构化简报，供后续问答",
    "files": ["SKILL.md", "scripts/parse.py"],
    "install_path": "~/.openclaw/skills/pdf-briefing"
  },
  "reason": "周报场景需要把 PDF 报告汇总成摘要"
}
```

字段约束：

| 字段 | 必填 | 上限 | 说明 |
|------|------|------|------|
| `kind` | 是 | — | `skill` 或 `mcp`（其它值 400） |
| `name` | 是 | 128 字符 | 唯一标识：skill 名 / mcp server 名 |
| `source` | 否 | 256 字符 | 来源（URL/市场/自研），展示给审批人 |
| `payload` | 否 | 序列化 ≤ 64KB 的 JSON 对象 | 申请明细，审批人详情里查看；建议至少含内容摘要 |
| `reason` | 否 | 2000 字符 | 使用理由，建议填写以加速审批 |

建议 `payload` 内容：skill → 摘要、文件清单、安装路径；mcp → server 定义摘要
（命令/URL、协议、工具数）、将被授予的权限范围。**不要**放密钥/令牌等敏感信息
（审批人与审计日志可见）。

成功响应：

```json
{ "data": { "request_id": 12, "state": "pending", "approve_mode": "manual" } }
```

`approve_mode=auto`（预留）表示系统配置了自动审批；`manual` 表示人工审批。

### 2.3 轮询审批结果

`GET /telemetry/v1/extensions/requests?limit=200`

```json
{
  "data": {
    "requests": [
      {
        "id": 12,
        "kind": "skill",
        "name": "pdf-briefing",
        "source": "https://…",
        "state": "approved",
        "approve_mode": "manual",
        "review_note": "",
        "reviewed_at": "2026-09-09T03:00:00Z",
        "created_at": "2026-09-09T02:00:00Z"
      }
    ]
  }
}
```

客户端行为要求：

1. 提交申请后按 **30 秒/次** 轮询直至该 `request_id` 状态非 `pending`
   （超时上限建议 24h；服务端不主动推送）。
2. `state=approved`：放行对应安装/接入动作。
3. `state=rejected`：**不得安装/接入**；把 `review_note`（驳回理由）展示给使用者，
   需要时可修改内容后重新上报（每次上报生成新审批单，同名不合并）。
4. `payload`、`reason` 字段仅为申请信息，轮询响应不含（不需要回显）。
5. 本地可保留“申请 → 结果”的本地记录用于重连后对账：以 `request_id` 为准，
   重复提交同一次安装会产生多条申请，审批人按单处理。

### 2.4 客户端异常行为

| 情形 | 行为 |
|------|------|
| 上报 5xx/超时 | 退避重试（复用 REMOTE.md §8 节奏），未确认成功前不安装 |
| 上报 400 | 修正参数后重试；持续失败则本地告警并跳过安装（不静默直装） |
| 服务端未启用该能力（404） | 记录告警；按本地策略降级（默认仍要求人工放行，避免绕过治理） |
| 断网期间收到本地安装指令 | 先尝试上报；网络不可达时**不执行安装**并提示“待审批/离线” |

---

## 3. Skill 分发（拉取 + 安装 + 回执）

### 3.1 感知有包待装：`skills_pending`

- **注册响应**（`POST /telemetry/v1/register`）与**心跳响应**
  （`POST /telemetry/v1/heartbeat`）均带 `skills_pending: true|false`。
- 为 `true` 表示存在“已分配但尚未同步”的包（新分配、内容升级到新版本、或上次
  安装失败未回执成功）。
- 客户端应在注册成功、心跳返回 `true` 时触发拉取；也可周期性（建议与心跳同
  周期）静默对账一次，不依赖标志位。
- 该标志位在管理端解除分配后不再返回该包（`false`）；**已安装的本地副本服务端
  不负责回收**，由本地策略决定保留或卸载（建议保留并标记“已解除托管”）。

### 3.2 拉取分配的包

`GET /telemetry/v1/skills`

```json
{
  "data": {
    "pending_count": 2,
    "skills": [
      {
        "package_id": 3,
        "name": "pdf-briefing",
        "description": "将 PDF 文档转成结构化简报",
        "version": 2,
        "zip_name": "pdf-briefing-v2.zip",
        "zip_size": 184320,
        "zip_base64": "UEsDBBQAAAAI…（zip 原样 base64）",
        "updated_at": "2026-09-09T02:00:00Z",
        "applied_version": 1,
        "applied_status": "ok",
        "applied_at": "2026-09-08T10:00:00Z"
      }
    ]
  }
}
```

| 字段 | 说明 |
|------|------|
| `zip_base64` | zip 原样 base64（解压后安装，服务端不解包内容） |
| `version` | 包当前版本（管理员每次覆盖上传 +1，从 1 起） |
| `applied_version` / `applied_status` / `applied_at` | 本终端最近一次回执（从未回执则为空） |
| `pending_count` | 本次响应中“待同步”包的数量（见下） |

“待同步”判定（客户端与服务端一致的口径）：

```
某包待同步 = 没有回执记录
          或 回执 status = failed
          或 回执 version < 当前 version
```

服务端将**全部已分配包**（不只增量）返回：内容量小（≤2MB/包），客户端应做
“版本对账 → 只安装需要更新的”幂等处理，而不是无脑全装。

### 3.3 安装与回执

安装流程（建议）：

1. 校验 base64 解码与 zip 完整性（CRC）；失败按“安装失败”回执。
2. 对比 `applied_version`：与当前版本一致且上次 `ok` → 跳过；
   `failed` → 重试；落后版本 → 安装新版。
3. 解压到本地 skill 目录（zip 顶层为单目录 = skill 名，见 SKILL_CREATION.md；
   安装时校验目录名防路径穿越：条目路径必须落在目标目录内）。
4. 安装成功 → `POST /telemetry/v1/skills/applied`；失败 → 同样回执失败。

`POST /telemetry/v1/skills/applied`

```json
{ "package_id": 3, "version": 2, "ok": true, "message": "" }
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `package_id` | 是 | 拉取响应中的包 id |
| `version` | 是 | 本次实际安装的包版本（必须与拉取到的 version 一致） |
| `ok` | 否 | true=成功；false=失败（缺省 true） |
| `message` | 否 | ≤1024 字符；失败原因/成功备注 |

响应：`{ "data": { "status": "ok" } }`。

失败回执后该包继续处于待同步：服务端在心跳/注册中继续标 `skills_pending=true`，
客户端按节奏（建议 5 分钟退避上限内）重试安装并再次回执；**不要**对同一版本
高频重试轰炸。

### 3.4 客户端异常行为

| 情形 | 行为 |
|------|------|
| 拉取失败（网络/5xx） | 下次心跳 `true` 或下一周期再试；不回执 |
| 对未分配给本终端的包回执 | 400 “该 skill 包未分配给本终端” —— 停止该包尝试 |
| 解压/安装失败 | 回执 `ok=false` + message；按节奏重试 |
| 已回执 `ok` 后包被升级（version+1） | 下次拉取见新版本 → 走增量安装 → 再回执 |
| 包被删除/解除分配 | 拉取不再返回；不强制卸载本地副本（本地自决） |

---

## 4. 与服务端契约对齐点（自检清单）

实现完成后请逐项自检：

- [ ] 安装新 skill / 接入新 MCP 前**一定**先上报申请（含 payload 摘要），无 `approved` 不安装；
- [ ] 申请后 30s 轮询直至非 pending；rejected 时展示 `review_note` 并阻止安装；
- [ ] 注册与心跳解析 `skills_pending`，为 true 即触发拉取流程；
- [ ] GET /skills 后按“版本对账”只装需要的包；装完（含失败）都回执；
- [ ] 回执失败/版本落后的包，会在下一次心跳再次收到 `skills_pending=true`；
- [ ] zip 解压做路径安全校验（防穿越），安装目录与包内结构一致；
- [ ] 全程遵循 REMOTE.md 的鉴权、错误码、时间格式与幂等/重试规范。

---

## 5. 参考：错误响应样例（与 REMOTE.md 统一）

```json
{ "error": { "message": "kind 仅支持 skill 或 mcp", "type": "invalid_request_error" } }
{ "error": { "message": "该 skill 包未分配给本终端", "type": "invalid_request_error" } }
{ "error": { "message": "extension governance not enabled", "type": "not_found_error" } }
```
