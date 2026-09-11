# Argus · AI Agent 全模态零信任安全守护平台

Argus 是一套面向 AI Agent（OpenClaw）的零信任安全守护平台，由三块组成：
**一个企业网关、一个终端防护运行时、一个桌面客户端**。

本仓库是三者的完整可运行源码（monorepo）。克隆下来按 [三步启动](#四三步启动) 即可跑通，
不需要再从别的仓库拉代码。

---

## 一、目录结构

| 目录 | 负责什么 | 技术栈 | 默认端口 |
|---|---|---|---|
| `gateway/` | 企业网关：账号体系、供应商与模型管理、Key 分配、终端管理、配额、用量与审计汇总 | Go 1.21+ · Gin · SQLite · Vue 3 + Vite | 8080 |
| `terminal/` | 终端防护运行时：访问控制、内容检测、ToolGuard、检索守卫；对接 OpenClaw，回传对话记录 / 行为审计 / LLM 用量 | Python 3.10+ · FastAPI | 8000 |
| `desktop/` | 桌面客户端：个人版直连本地，企业版走「网关 + 终端」链路；内置服务控制台与安装向导 | Electron 30 · Vue 3 · Vite | 5173（开发服） |
| `docs/` | 设计文档、测试报告、评审意见归档 | Markdown | — |

一句话记住分工：**桌面端是壳，终端是干活的，网关是管事的。**

---

## 二、数据怎么流（记住两句话）

1. **往下发**：网关把「用户等级、可用模型、LLM Key、终端配置」下发到终端，
   终端落到本地 `terminal/configs/remote.json`，断网也能按最后一次拿到的配置继续工作。
2. **往上报**：终端把「对话记录、行为审计、LLM 用量、心跳」定时推回网关，
   网关的审计页、用量页、成员监控页就齐了。

企业版调用链：

```
桌面端 → 终端 :8000 → 网关 :8080（统一鉴权 + 计费 + 配额）→ 上游供应商
```

切回个人版：桌面端直连本地终端，不再经过网关，Key 用自己配的。

---

## 三、环境要求

| 依赖 | 版本 | 用途 |
|---|---|---|
| Go | 1.21+（`go.mod` 声明 1.25） | 编译网关 |
| Python | 3.10+，建议 3.13 | 跑终端 |
| Node.js | 18+，建议 20/22 | 跑桌面端与网关前端 |

> Windows 上如果 PATH 里同时存在 Python 2.7，请显式用 `py -3` 或虚拟环境，
> 否则终端会起不来。

---

## 四、三步启动

三个服务各自开一个终端窗口，**都在仓库根目录下执行**。

### 第 1 步 · 启动网关

```powershell
cd gateway
go run cmd/server/main.go -config configs/config.yaml
```

打开 <http://127.0.0.1:8080>。
首次启动会自动建库（`gateway/data/llmgate.db`）并创建初始管理员：

```
账号：admin
密码：admin123
```

> 登录后请立刻改密码。
> Windows 上也可以直接双击 `gateway\start.bat`，它会自动编译并启动。

### 第 2 步 · 启动终端

```powershell
cd terminal
python -m pip install -r requirements.txt
python -m uvicorn clawguard.api.main:app --host 0.0.0.0 --port 8000
```

终端起来后监听 <http://127.0.0.1:8000>，这是 OpenClaw 兼容 API，
同时承担向网关回填对话 / 审计 / 用量的同步器。

### 第 3 步 · 启动桌面端

```powershell
cd desktop
npm install
npm run app:dev
```

`app:dev` 会先拉起 Vite（5173），就绪后再拉起 Electron 窗口。

### 一键启动（可选）

仓库根目录提供了 `start-argus.ps1`，会按顺序把三个服务分别放到独立窗口里启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-argus.ps1
```

加 `-SkipInstall` 可跳过依赖安装，加 `-GatewayOnly` / `-TerminalOnly` / `-DesktopOnly` 可只起其中一块。

---

## 五、第一次跑通的顺序建议

1. 起网关，用 `admin / admin123` 登录。
2. 在网关「供应商管理」里加上游供应商（填 Base URL + API Key），
   点「获取模型列表」拉 `/v1/models`，勾选要开放给成员的模型。
3. 在「终端管理」里新建终端，拿到注册码。
4. 起终端，用注册码在桌面端「企业版」里完成绑定；
   绑定成功后终端会自己在 `terminal/configs/remote.json` 写入身份。
5. 在「密钥管理」里给这个终端分配 Key，并限定它只能用哪几个模型。
   分配之后，OpenClaw 侧就只能走网关，不能再用本地自己配的模型。
6. 在「用户管理」里给成员设等级；在终端「修改配置 → 访问控制」里给这个终端配规则等级与资源规则。

---

## 六、端口总览

| 谁 | 端口 | 说明 | 改在哪 |
|---|---|---|---|
| 网关 | 8080 | 管理控制台 + 网关 API | `gateway/configs/config.yaml` |
| 终端 | 8000 | OpenClaw 兼容 API + 回填同步 | 启动参数 `--port` |
| 桌面开发服 | 5173 | `npm run app:dev` 的 Vite 页面 | `desktop/vite.config.js` |
| OpenClaw 网关 | 18789 | 桌面端按需拉起的本地 OpenClaw | `desktop/src/main/daemon.js` |

---

## 七、默认规则与配置

仓库里带的就是当前使用的默认规则，安装后开箱即用，之后可以自己改：

| 文件 | 内容 |
|---|---|
| `terminal/configs/modules.yaml` | 各防护模块总开关与参数 |
| `terminal/configs/policy.yaml` | IO 守卫策略 |
| `terminal/clawguard/modules/access_control/original/rules/resources.txt` | 资源访问控制规则（一行一条） |
| `terminal/clawguard/modules/io_guard/original/configs/default_policy.json` | 内容检测默认策略 |
| `terminal/clawguard/modules/retrieval_guard/original/a_url/whitelist.yaml` | 检索白名单 |
| `terminal/clawguard/modules/retrieval_guard/original/c_prompt/config.yaml` | 提示注入检测配置 |

> **关于 `users.txt`**：用户与等级由网关统一下发，终端本地不再维护 `users.txt`。
> 每个终端只对应一个用户，等级只有一个，在网关「终端管理 → 修改配置」里改。

---

## 八、不随仓库分发的文件（本地自动生成）

这些是**故意**不入库的，克隆下来没有它们是正常的：

- `gateway/data/` —— 网关数据库，含真实用户与 Key
- `terminal/configs/remote.json` —— 终端绑定身份，含 token 与 Key
- `terminal/openguard/original/{data,keys,.env}` —— 本地鉴权库与密钥对
- 各类 `node_modules/`、`runtime/`、`*.log`、编译出的 `*.exe`

仓库根目录 `.gitignore` 已经把这些全部挡住。
提交前如果想自查，可以搜一遍 `sk-` / `token` / `.pem`。

---

## 九、打包分发

### 网关（服务端）

```powershell
cd gateway\web
npm install
npm run build

cd ..
go build -o bin\llmgate.exe .\cmd\server\
```

`gateway/web/dist` 已经随仓库提交（Go 用 `embed` 内嵌），
所以即使不重新构建前端，直接 `go build` 也能得到一个自带控制台的单文件服务端。

### 桌面端（客户端）

```powershell
cd desktop
npm install
npm run package:exe     # 出 NSIS 安装包，产物在 desktop\release-nsis
# 或
npm run package:win     # 出免安装目录版，产物在 desktop\release
```

打包脚本会按 `package.json` 里的 `extraFiles` 把 `../terminal` 一起塞进安装目录，
安装后终端和桌面端是同级目录，桌面端 `daemon.js` 会自动找到它。

> 打包产物不进仓库。`desktop/release*`、`desktop/dist` 都已在 `.gitignore` 里。

---

## 十、目录内的详细文档

| 文档 | 讲什么 |
|---|---|
| `gateway/README.md` | 网关自身架构、接口与部署 |
| `gateway/CLIENT.md` | 网关对外开放的 API 契约 |
| `gateway/REMOTE.md` | 终端 ↔ 网关的远程协议（注册、心跳、上报） |
| `gateway/SKILL_CREATION.md` | Skill 包的打包与分发规范 |
| `terminal/README.md` | 终端防护模块逐个说明 |
| `terminal/docs/LLMGate对接方案.md` | 终端接入网关的对接设计 |
| `desktop/README.md` | 桌面端架构与开发方式 |
| `desktop/DESIGN.md` | 桌面端界面设计规范 |
| `docs/` | 设计、测试、评审报告归档 |

---

## 十一、常见问题

**Q：`go run` 报找不到 module？**
先确认在 `gateway/` 目录下执行。Go 依赖都在 `go.mod`，首次会自动下载。

**Q：终端起来了但桌面端连不上？**
检查 8000 端口是否被别的 Python 进程占用；再看 `terminal/runtime/` 下的日志。

**Q：企业版登录成功但 OpenClaw 还在用本地模型？**
说明这个终端还没在网关「密钥管理」里分配到 Key 和模型白名单。
分配后终端会通过 `remote_sync` 拉到新配置，桌面端会重写 OpenClaw 的 provider 指向网关。

**Q：审计 / 用量页是空的？**
终端要处于「企业版」绑定状态才会往网关回填。
登录网关看「终端管理」里该终端是否是在线；离线状态下数据会存在本地，等终端重新上线后补传。

---

## 十二、许可

MIT，见 [LICENSE](LICENSE)。
