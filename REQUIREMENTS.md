# Argus 运行环境与依赖清单（Requirements）

> 本文件回答一个问题：**把 Argus 拷到另一台机器，要准备什么才能正常跑起来。**
> 代码依赖的分项清单在各自语言目录（见 §2），本文件负责汇总 + **外部服务** + 自检 + 故障对照。

---

## 0. 一句话结论

需要一个 **Windows 10/11** 机器，装好 **Go ≥ 1.25 / Node ≥ 18 / Python ≥ 3.10**，
再加 **两个外部服务：Ollama（意图裁判 LLM）和 OpenClaw（智能体宿主）**，
然后 `start-argus.ps1` 一键起三件套。**Ollama 不准备会导致所有工具调用被拦。**

---

## 1. 必需运行时

| 组件 | 版本要求 | 用在哪 | 检查命令 |
|---|---|---|---|
| **Go** | **≥ 1.25**（`gateway/go.mod` 要求 `go 1.25.0`） | 企业网关（`:8080`） | `go version` |
| **Node.js + npm** | ≥ 18（实测 24.x 可用） | 桌面端 / 网关管理台 / OpenClaw 适配器插件 | `node -v`、`npm -v` |
| **Python** | ≥ 3.10（项目统一目标 **3.11.9**，实测 3.13 可用） | 终端防护运行时（`:8000`） | `py --version` |
| **Windows PowerShell** | 5.1+ | 一键启动器 / 桌面端启动脚本 | `$PSVersionTable` |
| 操作系统 | Windows 10/11 | 桌面端是 Electron/Win 产物 | — |

> **Go 找不到时的查找顺序**（启动器 `start-argus.ps1` 内置）：
> `$env:ARGUS_GO` → `<仓库>/tools/go/bin/go.exe` → `<仓库>/.tools/go-tmp/go/bin/go.exe`
> → 上级 `.tools/go-tmp/go/bin/go.exe` → PATH。
> 所以**便携版 Go 放到 `<仓库>/tools/go/` 即可免安装**。

---

## 2. 语言依赖（各目录已有清单，启动器会自动补齐）

| 语言 | 清单文件 | 安装命令 |
|---|---|---|
| Python（主） | `terminal/requirements.txt` | `py -m pip install -r terminal/requirements.txt` |
| Python（模块级） | `terminal/argus/modules/io_guard/requirements.txt`、`.../audit/requirements.txt` | 同上（启动器按需） |
| Go | `gateway/go.mod` | `go mod download`（在 `gateway/` 下） |
| Node（桌面端） | `desktop/package.json` | `npm install`（在 `desktop/` 下） |
| Node（网关管理台） | `gateway/web/package.json` | `npm install`（在 `gateway/web/` 下） |
| Node（适配器插件） | `terminal/openclaw_adapter/plugins/argus-adapter/package.json` | `npm install && npm run build` |

**一键补齐 + 启动**（推荐）：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-argus.ps1
# 加 -SkipInstall 可跳过依赖安装；加 -GatewayOnly / -TerminalOnly / -DesktopOnly 可只起一块
```

> 安装依赖**需要联网**（PyPI / npm / Go module proxy）。

---

## 3. 外部服务（**不在仓库内，必须单独准备**）

### 3.1 Ollama —— tool_guard 的意图裁判 LLM（**必需**）

| 项 | 内容 |
|---|---|
| 不准备会怎样 | tool_guard 判定 `llm_unconfigured` → 按 `on_error=block` **fail-closed**，**连良性的 `read_file` 也会被拦** |
| 安装 | 下载 https://ollama.com/download ，然后 `ollama pull dolphin3:8b`（或任意 instruct 模型） |
| 默认配置 | `terminal/configs/modules.yaml` 的 `tool_guard` 段已指向 `http://127.0.0.1:11434/v1`、`model: dolphin3:8b`（本地地址不需要 api_key） |
| 换模型 / 换云端 | 改 `modules.yaml` 的 `base_url` / `model` / `api_key`，或用环境变量覆盖：`TOOL_GUARD_LLM_BASE_URL`、`TOOL_GUARD_LLM_API_KEY`、`TOOL_GUARD_LLM_MODEL` |
| 阈值语义 | `score` 是**合规度**（越高越符合用户意图）：`< block_threshold` → block；`[block, review)` → human_review；`≥ review_threshold` → allow。**必须 `block_threshold < review_threshold`**（默认 0.4 / 0.7） |

### 3.2 OpenClaw —— 智能体宿主（**必需**，≥ 2026.6.11）

| 项 | 内容 |
|---|---|
| 启动 | 桌面端守护进程会自动拉起；也可手动 `openclaw gateway run`（默认 `:18789`） |
| 插件 | Argus 适配器位于 `terminal/openclaw_adapter/plugins/argus-adapter`；桌面端启动脚本会把它同步到 `%USERPROFILE%\.openclaw\extensions\argus-adapter`（含 dist + manifest） |
| 健康标志 | OpenClaw 网关日志出现 `[plugins] Argus API is healthy` |
| 关键配置 | 插件需 `argusUrl`（指向 `http://127.0.0.1:8000`）、`failMode: closed`；**键名必须是 `argusUrl`**（旧名 `clawguardUrl` 会被 schema 拒绝，导致网关启动失败） |

---

## 4. 可选增强（不装也能跑，能力降级）

| 项 | 不装的影响 | 安装方式 |
|---|---|---|
| **PIGuard 权重 + torch** | `retrieval_guard` 的 B 层（语义注入检测）不生效：随包已配 `guards.B: false`；评测集中依赖 B 层的 14 条会记为「未覆盖」而非判定失败 | `pip install -r terminal/argus/modules/retrieval_guard/requirements.txt`（torch/transformers），再从 HuggingFace `leolee99/PIGuard` 拉到 `terminal/argus/modules/retrieval_guard/models/PIGuard`，最后把 `modules.yaml` 的 `guards.B` 改回 `true` |
| 网关管理台前端产物 | 已随仓库提交（`gateway/web/dist`，`go:embed` 需要），**无需额外构建** | — |

### 运行期自动生成（无需准备，首次启动自动创建）

| 路径 | 内容 |
|---|---|
| `gateway/data/llmgate.db` | 网关 SQLite 库；首次启动自动建表并创建 `admin / admin123` |
| `terminal/runtime/` | 审计事件、用量、隔离状态等运行时数据 |
| `desktop/node_modules`、`desktop/dist` | 桌面端依赖与构建产物（`npm install` / `npm run build` 生成） |
| `%USERPROFILE%\.openclaw\` | OpenClaw 状态目录（配置、会话、插件） |

> 说明：**io_guard 的阶段感知字符分类器权重已随仓库提交**（`terminal/argus/modules/io_guard/original/model_heads/io-guard-stage-char-v3/`，2.6MB），开箱即可用。

---

## 5. 出场前自检（4 步）

```powershell
# 1) 一键启动（首次会自动装依赖，需联网）
powershell -ExecutionPolicy Bypass -File .\start-argus.ps1

# 2) 健康检查：三个服务都应在监听
curl.exe http://127.0.0.1:8080/health     # 企业网关
curl.exe http://127.0.0.1:8000/health     # 终端运行时（应返回 5 个模块 ok）
curl.exe http://127.0.0.1:18789/health    # OpenClaw 网关

# 3) 评测集基线（不带 --repo 会自动探测 <仓库根>/terminal）
cd testset
py eval_dataset.py --all
# 参考基线：审计 100% / 沙箱 96.6% / 多用户认证 92.9% / 输入 83.9% / 访问控制 74.7% …
#          工具安全需配 §3.1 的 LLM，否则裁判未配会整体拦

# 4) OpenClaw 真实链路（可选）：良性读取应成功，危险命令应被拦
openclaw agent --agent main -m "用 read 工具读取 C:\Windows\win.ini 的前两行"
openclaw agent --agent main -m "用 exec 执行 echo hello"
```

---

## 6. 常见故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动器报「找不到 go」 | 未装 Go 或不在 PATH | 装 Go ≥ 1.25，或把便携版放到 `<仓库>/tools/go/` |
| 网关窗口一闪就退 | Go 版本低于 `go.mod` 要求 | 升级到 Go ≥ 1.25 |
| 桌面端窗口秒退（退出码 0） | 已有同 userData 的实例占着**单实例锁**，或 5173/8000 被占 | 关掉旧的 Argus/Clawguard 进程后再启动 |
| 首页三格显示「连接失败」 | 服务还没起齐（正常）或没起 | 等 30~40s 会自动重试；仍失败看 `desktop` 守护日志 |
| **所有**工具调用返回 `llm_unconfigured` | Ollama 没启动 / 模型没 pull | 见 §3.1 |
| 所有工具调用返回 `quarantined: ...` | 风险联动把该账号**隔离**了（连续试探触发） | `POST http://127.0.0.1:8000/v1/admin/quarantine/clear`，body `{"user_id":"<账号>","reason":"release"}` |
| 白名单网页也读不回来 | C 层包装语与 context 检测冲突（历史问题，已修） | 确认 `terminal/argus/modules/retrieval_guard/original/c_prompt/config.yaml` 为当前版本 |
| OpenClaw 网关启动报 `must not have additional properties` | 安装的插件副本比仓库旧（manifest schema 与代码不一致） | 重新同步：把 `terminal/openclaw_adapter/plugins/argus-adapter` 的 dist+manifest 覆盖到 `%USERPROFILE%\.openclaw\extensions\argus-adapter` |
| OpenClaw agent 报 `Model override ... is not allowed` | 该模型不在 `agents.defaults.models` 白名单 | 在 `~/.openclaw/openclaw.json` 的 `agents.defaults.models` 里补上该模型 |
