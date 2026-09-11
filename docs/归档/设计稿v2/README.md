# Clawguard 访问控制网关 — 架构与实现报告

> **项目**：挑战杯 · 访问控制网关  
> **版本**：v2（最终提交版）  
> **作者**：[留空]  
> **日期**：2026 年 7 月

---

## 一、项目概述

Clawguard 是一个与 AI 网关（OpenClaw）集成的访问控制模块，核心目标是为 AI Agent 的工具调用、文件读写、数据库访问等操作提供最小粒度的安全管控。

### 设计原则（对接需求方 刘欣亚 的明确要求）

1. **极简接口**：对外只暴露一个函数 `check(user_id, path, tool, database) -> bool`
2. **规则外置**：权限规则用最简单的竖线 `|` 分割文本文件，一行一条，不写死在代码里
3. **双机制管控**：等级比对 + 特例覆盖，砍掉注入检测、Recurse、OPA 等周边功能
4. **零依赖**：纯 Python 标准库实现，不依赖 Flask、Redis、PostgreSQL 等外部组件
5. **热更新**：修改规则文件后调用 `reload_rules()` 即可生效，无需重启进程

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│                        OpenGuard                             │
│                    (FastAPI, port :3000)                     │
│                                                              │
│  Browser ──► JWT 验证 ──► sync_external_user() ──► HTTP     │
│                │                    │              Proxy    │
│                │              ┌─────▼──────┐       │        │
│                │              │ auth_gateway│       │        │
│                │              │  .check()   │       │        │
│                │              │             │       │        │
│                │              │ RuleStore   │       │        │
│                │              │ ┌─────────┐ │       │        │
│                │              │ │users.txt│ │       │        │
│                │              │ │res.txt  │ │       │        │
│                │              │ └─────────┘ │       │        │
│                │              └─────┬──────┘       │        │
│                │                    │              │        │
│                │              ✅ ALLOW?            │        │
│                │                    │              │        │
│                ▼                    ▼              ▼        │
│          ┌──────────────────────────────────────────┐       │
│          │          OpenClaw AI Gateway              │       │
│          │              (port :18789)                │       │
│          │         DeepSeek V4 Pro / etc.           │       │
│          └──────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

### 调用关系

```
HTTP 请求到达 → proxy.py 的 proxy_to_openclaw()
    │
    ├─ 1. auth_middleware()      → 验证 JWT，解析 user_id + security_level
    ├─ 2. sync_external_user()   → 将用户等级注入 RuleStore（热注入，无需预设）
    ├─ 3. check(user_id, path)   → 🛡️ 访问控制判定
    │       ├─ 用户等级解析
    │       ├─ 特例规则匹配（allow / block）
    │       └─ 等级比对（user_level >= resource_level）
    ├─ 4. ALLOW → 转发到 OpenClaw
    └─ 5. BLOCK → HTTP 403 + 拦截原因
```

---

## 三、核心数据结构

### 3.1 用户规则文件（users.txt）

```
# 格式: 用户ID | 等级 | 特例(可选,逗号分隔)
# ! 前缀 = 显式禁止

admin_01    | top_secret | *
user_01     | internal   |
intern_01   | public     | tool:query_weather
auditor_01  | internal   | !tool:write_file, tool:read_file
guest_01    | public     | /public/*
```

### 3.2 资源规则文件（resources.txt）

```
# 格式: 资源模式 | 所需等级

/data/secret/*      | top_secret
/etc/*               | top_secret
tool:execute_bash    | top_secret
db:huawei_db         | top_secret
tool:write_file      | secret
/channels            | top_secret
/admin/*             | top_secret
tool:read_file       | internal
/data/reports/*      | internal
tool:query_weather   | public
db:public_db         | public
/public/*            | public
```

### 3.3 等级体系

| 数值 | 别名 | 含义 |
|---|---|---|
| 1 | `public`, A | 公开 |
| 2 | `internal`, B | 内部 |
| 3 | `secret`, C | 机密 |
| 4 | `top_secret`, D | 绝密 |

### 3.4 资源类型

`check()` 支持三类资源输入，任一命中即可：

| 参数 | 类型 | 示例 |
|---|---|---|
| `path` | 文件/目录路径 | `/data/reports/q3.txt` |
| `tool` | 工具 ID | `tool:execute_bash` |
| `database` | 数据库名 | `db:huawei_db` |

---

## 四、核心实现细节

### 4.1 RuleStore — 规则缓存层

```python
class RuleStore:
    """规则缓存。改动文件后调用 reload() 即可热更新，无需重启。"""

    def __init__(self, users_file, resources_file):
        self.users: dict[str, dict] = {}          # user_id → {level, specials}
        self.resources: list[tuple[str, int]] = [] # [(pattern, required_level), ...]
        self.reload()

    def reload(self):
        self.users = self._load_users(self.users_file)
        self.resources = self._load_resources(self.resources_file)
```

**设计要点**：
- 用户表用 `dict`（O(1) 查找），资源表用 `list`（顺序扫描，少量条目无需索引优化）
- 解析时自动跳过空行和 `#` 注释行
- 等级字段通过 `_normalize_level()` 做别名映射，支持数字、字母、英文名三种写法
- `set_user_level()` 支持外部注入用户等级（用于对接外部认证系统）

### 4.2 _match_pattern() — 模式匹配引擎

```python
def _match_pattern(pattern: str, value: str) -> bool:
    """支持三种语义：
      1. glob 通配符: /data/*  → 按 fnmatch 匹配
      2. 工具前缀:    tool:*   → 前缀匹配（如 tool:write_file）
      3. 子串匹配:    /etc     → 包含即命中
    """
```

**设计要点**：
- 通配符 `*` 和 `?` 触发 `fnmatch`（Python 标准库的文件名通配匹配）
- 包含 `:` 的 pattern 按工具/数据库命名空间精确匹配
  - `tool:*` 匹配 `tool:write_file`、`tool:read_file` 等所有工具
  - `tool:write_file` 只匹配精确工具
- 其他情况按子串包含匹配，适配路径

### 4.3 判定流程 — check() 核心逻辑

```
check(user_id, path, tool, database)
│
├─ 1. 空请求检查：path/tool/database 全空 → BLOCK
│
├─ 2. 解析用户等级：
│     ├─ 用户不在 users.txt 且未通过 sync_external_user() 注入
│     │   ├─ BLOCK_UNKNOWN_USERS=true  → BLOCK
│     │   └─ BLOCK_UNKNOWN_USERS=false → 默认等级 1 (public)
│     └─ 用户在用户表中 → 获取等级
│
├─ 3. 特例优先判定（可越级放行，也可显式拒绝）：
│     ├─ 特例 !xxx 匹配 → BLOCK（显式拒绝，不可覆盖）
│     └─ 特例 xxx 匹配  → ALLOW（越级放行）
│
└─ 4. 等级比对：
      user_level >= resource_required_level → ALLOW
      否则 → BLOCK
```

**关键设计决策**：

1. **特例优先于等级**：特例即使匹配，`!` 拒绝规则也能覆盖等级放行。这确保了安全策略是 Fail-Safe 的——管理员可以显式禁止某个用户访问某类资源，即使该用户等级够高。

2. **特例允许可越级**：`intern_01` (等级 1) 可以通过特例 `tool:query_weather` 访问本该需要更高等级的工具——特例就是"特别通行证"。

3. **安全兜底**：空请求（三个参数全空）直接拒绝，防止未指定目标的操作。

### 4.4 sync_external_user() — 外部认证集成

```python
def sync_external_user(user_id: str, security_level: str) -> None:
    """从外部认证系统（如 JWT / SQLite）同步用户等级到规则引擎。"""
    level = _normalize_level(security_level)
    _store.set_user_level(user_id, level)
```

**设计要点**：
- 对接同学的多用户模块时，从 JWT 中解析出 `user_id` + `security_level`，注入到 RuleStore
- 如果 `users.txt` 中已有该用户的特例规则，保留特例仅更新等级；否则新建一条纯等级记录
- 这意味着用户不需要同时维护两套用户表——等级可以来自外部，特例仍然由本地规则文件管理

### 4.5 热更新

```python
def reload_rules() -> None:
    """外部修改规则文件后调用，热更新。"""
    _store.reload()
```

修改 `users.txt` 或 `resources.txt` 后，调用 `python auth_gateway.py reload` 即可热更新规则，无需重启网关。

---

## 五、在 OpenGuard 网关中的集成

### 5.1 集成位置

在 [proxy.py](proxy.py) 的 `proxy_to_openclaw()` 函数中，在 JWT 验证之后、请求转发之前插入：

```python
# -------- 🛡️ Clawguard 访问控制 --------
# 从 JWT 中的 security_level 同步到规则引擎
sync_external_user(user.user_id, user.security_level)

# 提取目标路径作为被访问资源
target_path = _build_target_path(request)

# 访问控制判定
allowed, reason = check_reason(
    user_id=user.user_id,
    path=target_path,
)
if not allowed:
    raise HTTPException(
        status_code=403,
        detail={"error": "access denied", "reason": reason, "code": "ACCESS_DENIED"}
    )
# ----------------------------------------
```

### 5.2 实际展示

以下是在 OpenClaw 聊天中，用户请求"访问磁盘的 Windows 文件夹"时的拦截日志：

```
[Clawguard] BLOCK user=adminuser path=/etc/hosts → block: 用户等级 4 < 资源所需 4
```

Clawguard 在网关层拦截了该请求，Agent 无法执行 Shell 命令访问文件系统。用户关闭插件后恢复正常。

---

## 六、模块边界与职责

| 模块 | 职责 | 依赖 |
|---|---|---|
| `auth_gateway.py` | 规则引擎核心：解析规则、匹配、判定 | 无（标准库） |
| `proxy.py` | OpenGuard HTTP/WS 代理层，调用 check() | auth_gateway, JWT |
| `main.py` | FastAPI 主入口，路由注册，WebSocket 聊天 | proxy, auth_gateway |
| `bridge.js` | WebSocket 桥接（OpenGuard ↔ OpenClaw），Ed25519 握手 | 无 |
| `rules/users.txt` | 用户等级 + 特例配置 | 无（纯文本） |
| `rules/resources.txt` | 资源所需等级配置 | 无（纯文本） |

---

## 七、扩展能力

1. **多外部认证源**：`sync_external_user()` 可被任意认证中间件调用，不限于 JWT
2. **运行时规则管理**：未来可通过 API 写入 `users.txt` + `reload_rules()` 实现 Web 管理面板
3. **审计日志**：`check_reason()` 返回的 `(bool, str)` 可直接写入审计日志做追溯
4. **通配符规则**：`fnmatch` 支持标准 Unix glob，`/data/*/secret/*.txt` 等复杂模式
5. **工具命名空间**：`tool:*` 前缀匹配支持工具组的批量管控

---

## 八、文件清单

```
v2/
├── auth_gateway.py          # 核心模块（318 行）
├── test_auth_gateway.py     # 单元测试（14 用例）
├── test_e2e.py              # 端到端测试（12 用例，需网关运行）
├── rules/
│   ├── users.txt            # 用户规则
│   └── resources.txt        # 资源规则
└── README.md                # 本报告
```
