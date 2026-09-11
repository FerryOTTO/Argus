# Argus Gateway · 企业网关

Argus 三件套里的「管事的」那一件。
负责账号、供应商与模型、Key 分配、终端管理、配额、用量与审计汇总，
并用一套统一鉴权把终端发起的模型调用转发到上游供应商。

---

## 一、职责边界

| 网关负责 | 网关不负责 |
|---|---|
| 账号、角色、SSO、JWT | 真正执行内容检测与访问控制（那是 `../terminal` 的事） |
| 上游供应商与模型清单（`/v1/models` 拉取 + 勾选） | 采集本机文件、进程行为 |
| 给终端分配 LLM Key，并限定可用模型 | 界面交互（那是 `../desktop` 的事） |
| 终端注册、心跳、配置下发 | |
| 对话记录、行为审计、LLM 用量的接收与展示 | |
| 配额与限流、统一计费口径 | |
| Skill 包的打包、审批与分发 | |

---

## 二、技术栈与目录

Go 1.21+ · Gin · SQLite · Vue 3 + Vite。

```
gateway/
├── cmd/server/         程序入口（含首次启动创建默认管理员）
├── internal/
│   ├── auth/           JWT、密码、OAuth2 / OIDC / 本地账号
│   ├── config/         配置加载
│   ├── crypto/         Key 加密存储
│   ├── handler/        HTTP 接口（管理端 + 遥测端）
│   ├── middleware/     鉴权、RBAC、配额、限流、审计
│   ├── model/          数据模型
│   ├── proxy/          转发上游、流式透传、协议转换
│   ├── response/       统一响应格式
│   ├── service/        业务逻辑（Key、配额、审批、Skill 打包）
│   ├── static/         内嵌前端静态资源
│   └── store/          数据访问层（SQLite）
├── migrations/         SQL 迁移，按序号执行
├── web/                Vue 3 管理控制台
│   ├── src/            源码
│   └── dist/           构建产物（已提交，用 go:embed 内嵌）
├── configs/config.yaml 端口、数据库路径、JWT 密钥
├── CLIENT.md           对外 API 契约
├── REMOTE.md           终端 ↔ 网关远程协议
└── SKILL_CREATION.md   Skill 包规范
```

---

## 三、启动

```powershell
cd gateway
go run cmd/server/main.go -config configs/config.yaml
```

或者双击 `start.bat`（自动编译 + 启动）。

默认监听 `http://127.0.0.1:8080`，首次启动会自动：

1. 建库 `data/llmgate.db`；
2. 跑 `migrations/` 下所有未执行的迁移；
3. 创建初始管理员 **admin / admin123**（见 `cmd/server/main.go` 的 `ensureDefaultAdmin`）。

> 生产环境请先改两处：
> `configs/config.yaml` 里的 `server.jwt_secret`（默认 `change-me-in-production`）和 `security.encrypt_key`；
> 以及登录后立刻改掉管理员密码。

---

## 四、编译成单文件

```powershell
cd web
npm install
npm run build

cd ..
go build -o bin\llmgate.exe .\cmd\server\
```

`web/dist` 已经随仓库提交，Go 通过 `web/embed.go` 把它内嵌进二进制，
所以**不重新构建前端也能直接编译**，产物是一个自带控制台的 exe。

也可以直接 `make build`。

---

## 五、配置说明（`configs/config.yaml`）

| 字段 | 说明 |
|---|---|
| `server.port` | 监听端口，默认 8080 |
| `server.jwt_secret` | JWT 签名密钥，**上线必须改** |
| `server.jwt_expiry` | 登录态有效期，默认 24h |
| `server.cors_origins` | 允许的跨域来源 |
| `database.path` | SQLite 文件路径，默认 `./data/llmgate.db` |
| `log.level` | 日志级别 |
| `audit.retention_days` | 审计记录保留天数，默认 90 |
| `conversation.retention_days` | 对话记录保留天数，默认 90 |
| `security.encrypt_key` | 供应商 Key 的加密密钥，**上线必须改** |
| `security.login_max_retries` | 登录失败上限 |
| `security.lockout_duration` | 锁定时间 |

---

## 六、给终端用的两个接口面

网关对终端暴露的接口统一挂在 **`/telemetry/v1`** 前缀下，细节见 `REMOTE.md`。

**下发方向**

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/telemetry/v1/register` | 用注册码绑定终端，返回 token 与一次性下发的 LLM 凭据 |
| GET | `/telemetry/v1/config` | 拉取最新配置：用户等级、可用模型、Key、规则、Skill 分配 |
| POST | `/telemetry/v1/config/applied` | 回执「配置已应用」，网关记录生效时间 |
| POST | `/telemetry/v1/heartbeat` | 心跳保活，刷新在线状态 |

**上报方向**

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/telemetry/v1/report` | 运行数据上报：对话记录 + LLM 用量（token 数、模型、耗时） |
| POST | `/telemetry/v1/audit/events` | 行为审计事件批量上传，按 `(终端, event_id)` 幂等去重 |

另有扩展治理相关：
`POST /telemetry/v1/extensions/requests`（申请 MCP / Skill）、
`GET /telemetry/v1/skills`（拉取分配给本终端的 Skill）、
`POST /telemetry/v1/skills/applied`（回执已应用）。

终端侧对应的实现在 `../terminal/argus/api/remote_sync.py`，默认 60 秒一轮。

**管理端接口**（控制台用，前缀 `/api/admin`）：`terminals`、`providers`、`api-keys`、
`users`、`quotas`、`audit-events`、`conversations`、`dashboard`、`extensions/*` 等，
完整清单见 `internal/handler/router.go`。

---

## 七、对话 / 审计 / 用量是怎么进到仪表盘的

1. 终端在本地产生记录，先落本地库（断网也不丢）。
2. `remote_sync` 按增量游标把新记录推给网关。
3. 网关 `internal/handler/telemetry_*.go` 落库，游标持久化。
4. 管理控制台的仪表盘、审计页、用量页直接查库。
5. 「今日」口径统一按**北京时间（UTC+8）**切分，见 `internal/store/beijing.go`。

---

## 八、和其他两块的约定

- 网关不直接读终端本地文件，一切通过上面两张接口表。
- 终端断线期间的数据留在本地，重新上线后按游标补传，网关按 `event_id` 去重。
- 删除终端时，网关会一并删除该终端名下的审计记录与 LLM Key。

---

## 九、测试

```powershell
go test ./internal/...
```

端到端遥测链路可参考 `e2e_telemetry_test.sh`。
