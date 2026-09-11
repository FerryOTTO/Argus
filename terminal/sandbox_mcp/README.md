# Sandbox MCP

把「命令执行」和「文件读取」放进 Docker 容器里跑，再通过 MCP 协议暴露给 OpenCode / OpenClaw。

它是 Argus 的**执行侧隔离层**：Argus 负责「判断该不该拦」，Sandbox 负责「就算放行了也只在一个一次性容器里动手」。

## 1. 它能干什么

对外只暴露两个 MCP 工具：

| 工具 | 作用 | 跑在哪 |
|---|---|---|
| `sandbox_exec` | 执行一条 shell 命令，返回 stdout / stderr / 退出码 | `sandbox-exec:latest` 容器 |
| `sandbox_read` | 读取一个文件的内容 | `sandbox-file:latest` 容器 |

每次调用都是**新容器**，跑完即弃；带 CPU / 内存 / 进程数 / 超时 / 输出体积上限。所有命令在落到容器之前，还会先过一遍 `harm_detector.py` 的静态危害检测。

## 2. 目录结构

```text
sandbox_mcp/
├── README.md                    # 本文件
├── response.example.json        # sandbox_exec 的返回体示例
└── original/                    # 原始实现
    ├── sandbox_mcp_server.py    # MCP 服务（stdio 传输）
    ├── sandbox_mcp_http.py      # MCP 服务（HTTP 传输，默认 127.0.0.1:9876）
    ├── sandbox_mcp_sse.py       # MCP 服务（SSE 传输）
    ├── sandbox_exec.py          # 容器内命令执行器
    ├── sandbox_file.py          # 容器内文件读取器
    ├── harm_detector.py         # 危害静态检测
    ├── sandbox_config.yaml      # 镜像、资源限额、超时
    ├── check_env.py             # 环境自检（WSL2 + Docker + 镜像）
    └── opencode_sandbox.sh      # 容器内入口脚本
```

## 3. 环境要求

1. **Windows + WSL2**，发行版名称默认 `Ubuntu-24.04`；
2. **Docker Desktop**，且已把 WSL2 后端接上；
3. 两个镜像：`sandbox-exec:latest`、`sandbox-file:latest`。

先自检，别猜：

```powershell
cd terminal\sandbox_mcp\original
python check_env.py          # 人类可读
python check_env.py --json   # 机器可读，返回码 0 表示就绪
python check_env.py --fix    # 尝试自动开启 WSL2 等
```

发行版名、镜像名、资源限额都在 `original/sandbox_config.yaml` 里改。

## 4. 启动方式

三种传输方式按需选一种，**默认用 HTTP**（Argus 的 `configs/modules.yaml` 就是这么配的）。

### 4.1 HTTP（推荐，默认端口 9876）

```powershell
cd terminal\sandbox_mcp\original
python sandbox_mcp_http.py --host 127.0.0.1 --port 9876
```

接入 OpenCode：

```bash
opencode mcp add sandbox --url http://localhost:9876/mcp
```

端点：`POST /mcp`（JSON-RPC），`GET /` 与 `GET /mcp` 用于探活，已开 CORS。

### 4.2 stdio（由客户端托管进程）

```bash
opencode mcp add sandbox --command "python sandbox_mcp_server.py"
```

> 用绝对路径更稳，且 `python` 要指向 Python 3.10+（Windows 上 `python` 可能是 2.7，用 `py -3` 或写全路径）。

### 4.3 SSE

```powershell
cd terminal\sandbox_mcp\original
python sandbox_mcp_sse.py --host 127.0.0.1 --port 9876
```

## 5. 返回体长什么样

`sandbox_exec` 返回（完整示例见 `response.example.json`）：

```json
{
  "stdout": "",
  "stderr": "",
  "exit_code": 0,
  "timed_out": false,
  "execution_time_ms": 128,
  "blocked": false,
  "block_reason": "",
  "success": true,
  "harm_report": {
    "is_safe": true,
    "blocked": false,
    "severity": "safe",
    "match_count": 0,
    "matches": [],
    "summary": "未命中危害规则"
  }
}
```

| 字段 | 含义 |
|---|---|
| `blocked` / `block_reason` | 是否被 `harm_detector` 拦下及原因。被拦时命令**不会**进容器 |
| `timed_out` | 是否超过 `sandbox_config.yaml` 里的 `exec.timeout` |
| `execution_time_ms` | 容器内实际耗时 |
| `harm_report.severity` | `safe` / `low` / `medium` / `high` |

## 6. 和其他模块的关系

```text
OpenClaw / OpenCode
        │  MCP
        ▼
   Sandbox MCP  ──►  Docker 容器（sandbox-exec / sandbox-file）
        ▲
        │ 访问控制 + 审计事件
   Argus 运行时（terminal/argus）
```

- 配置项：`terminal/configs/modules.yaml` → `sandbox.url`（默认 `http://127.0.0.1:9876`）；
- 本地配置文件路径映射：`terminal/argus/api/local_config_routes.py` 里的 `"sandbox"` 条目；
- 审计归类：`terminal/argus/modules/audit/original/query.py` 已把 `sandbox` / `sandbox_mcp` 视为同类来源。

## 7. 常见问题

**`check_env.py` 报 `docker: false`？**
Docker Desktop 没启动，或没勾选 WSL2 集成。先手动把 Docker Desktop 拉起来再测。

**报镜像不存在？**
两个镜像需要本地构建/导入，`check_env.py` 的 `docker_image` 字段会明确告诉你缺哪个。

**端口 9876 被占？**
`python sandbox_mcp_http.py --port 9877`，同时改 `terminal/configs/modules.yaml` 里的 `sandbox.url`，两边要一致。

**超时太短/太长？**
改 `original/sandbox_config.yaml` 的 `exec.timeout`（秒），也可以在 `sandbox_exec` 调用时按次传 `timeout`。
