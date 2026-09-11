# Argus 访问控制模块 (Access Control) 说明文档

Argus 访问控制模块是智能体执行安全的第一道防线，负责在**工具调用前（`tool_pre`）**对用户身份、操作目标（工具/文件路径/数据库）进行严格的权限鉴权，并与**审计风险态势**深度闭环联动，实现自适应防线动态升级与人工二次审批。

---

## 一、 核心功能与架构

1. **多模型访问控制引擎**：
   * **RBAC（基于角色的访问控制）**：支持 4 个密级等级继承判定、通配符路径匹配与用户独立特例规则；
   * **MAC（强制访问控制）**：基于安全标签（等级 + 范畴集）的支配关系（Dominance）判定；
   * **Hybrid（混合模式）**：RBAC 与 MAC 双重校验，必须同时通过方可放行。
2. **审计风险联动与自适应防线（v5 新增）**：
   * 实时监听审计事件流，滑动时间窗统计近期拦截次数与高风险操作；
   * 动态计算用户风险评分，触发防线等级惩罚（`penalty`）；
   * 将原本放行但因防线升级而不满足条件的请求优雅降级为 **`human_review`（二次审批）**。
3. **高可用容错设计（Fail-Open）**：
   * 当审计存储出现异常或竞争超时时，自动降级为静态访问控制判定，绝不阻断正常业务。

---

## 二、 规则配置与等级管理

### 2.1 规则文件位置

```text
argus/modules/access_control/original/rules/users.txt      # 用户密级规则
argus/modules/access_control/original/rules/resources.txt  # 资源与工具密级规则
```

### 2.2 四级安全密级定义

| 等级数值 | 英文标识 | 密级名称 | 典型权限范围与工具 | 资源路径示例 |
| :---: | :--- | :--- | :--- | :--- |
| **1** | `public` | 公开级 | 只读公开信息：`query_weather`, `web_search`, `web_fetch`, `db:public_db` | `C:\Users\Public\*`, `/var/www/*` |
| **2** | `internal` | 内部级 | 普通员工权限：`read_file`, `read`, `list_dir`, `db:internal_db` | `C:\Users\admin\Desktop\*`, `/tmp/*` |
| **3** | `secret` | 秘密级 | 涉密人员权限：`write_file`, `write`, `delete_file`, `http_request`, `db:secret_db` | `C:\Program Files\*`, `/etc/*`, `*.log` |
| **4** | `top_secret` | 绝密级 | 超级管理员权限：`execute_bash`, `exec`, `bash`, `code_interpreter`, `*` | 全系统目录、`C:\Windows\*`, `*.pem`, `*.key` |

---

### 2.3 如何配置与修改用户等级

#### 方式 1：通过 OpenGuard 管理后台修改（推荐，免重启热生效）

系统已全面实装 Web 管理控制台（浏览器访问 `http://127.0.0.1:3000/admin`）：
* **途径 A（用户管理面板行内即时修改）**：在“用户管理”列表中找到目标用户，直接在其行内的“权限等级”下拉选择框中切换密级（`public` / `internal` / `secret` / `top_secret`）。系统将自动触发原子更新，持久化至 SQLite 数据库并毫秒级同步至规则引擎；
* **途径 B（规则修改专属 Tab）**：切换至顶部的“规则修改”Tab，可在专用的规则可视化表格中查看、添加或编辑任一用户规则，支持一键点击“保存”，规则引擎在下一秒内自动完成重载，运行中的 Agent 工具鉴权即刻按新规则判定生效。

#### 方式 2：直接编辑规则文件（离线维护）

直接编辑规则文本文件（Argus 规则引擎后台具备基于 `mtime` 的毫秒级文件变动自动热重载能力）：
* 文件路径：`argus/modules/access_control/original/rules/users.txt`
* 格式规范：`用户ID/用户名/AgentID | 等级(1~4 或 英文) | 特例权限(可选，逗号分隔)`

```text
# 示例:
intern_01 | public      |                       # 1 级 (公开)
user_01   | internal    |                       # 2 级 (内部)
user_sec  | secret      |                       # 3 级 (秘密)
admin_01  | top_secret  | *                     # 4 级 (绝密，拥有全通配权限)
alice     | secret      | !/data/secret/ceo.key # 3 级但显式禁止访问 ceo.key
```

#### 方式 3：使用 CLI 命令行工具一键修改（开发者快速调试）

```powershell
# 语法: py auth_gateway.py add-user <用户ID> <等级> [特例...]
py argus/modules/access_control/original/auth_gateway.py add-user alice secret

# 查看当前所有用户规则
py argus/modules/access_control/original/auth_gateway.py demo
```

---

## 三、 审计风险联动与动态防线（Dynamic Defense Escalation）

### 3.1 实时风险评分计算

`AuditRiskMonitor` 在滑动时间窗（默认 300 秒）内提取用户近期审计事件：

$$
R = \min\left(1.0,\; 0.4 \cdot \overline{R} + 0.3 \cdot \frac{N_b}{3} + 0.3 \cdot \frac{N_h}{3}\right)
$$

纯文本公式对照：
```text
risk_score = min(1.0, 0.4 * avg_risk + 0.3 * (block_count / 3) + 0.3 * (high_risk_count / 3))
```

* **变量说明**：`R` 为当前风险评分，`\overline{R}` 为平均风险，`N_b` 为拦截次数，`N_h` 为高风险事件数。当 `block_count >= 3` 时，系统标记 `probe_likely = True`（识别为频发试探行为）。

### 3.2 动态防线惩罚梯度

根据实时风险评分计算防线提升惩罚等级（`penalty`）：

$$
P = 
\begin{cases} 
2, & R \ge 0.85 \\ 
1, & 0.50 \le R < 0.85 \\ 
0, & R < 0.50 
\end{cases}
$$

纯文本公式对照：
```text
if risk_score >= 0.85: penalty = 2
elif risk_score >= 0.50: penalty = 1
else: penalty = 0
```

### 3.3 决策矩阵

计算目标资源所需等级：`required_level = base_required + penalty`。

| 基础判定 (`base_allowed`) | 升级后判定 (`escalated_allowed`) | 最终动作 (`action`) | 机制说明 |
| :--- | :--- | :--- | :--- |
| `False`（原本就越权） | `False`（越权） | **`block`** | 最高防线不变，物理阻断并记录审计事件 |
| `True`（原本合法） | `True`（依然够格） | **`allow`** | 防线收紧后用户权限依然足够高（如管理员），直接放行 |
| `True`（原本合法） | `False`（升级后不够格） | **`human_review`** | 触发防线升级，转人工二次审批 |

### 3.4 近永久隔离区工程体系（Quarantine Store & API）

为应对低频、慢速探测攻击与跨窗口持续试探，模块实装了生产级近永久隔离区机制（`quarantine_store.py` 与 `quarantine_routes.py`），支持基于状态机的三因子联合判据：

$$
Q = (N_{b,5m} \ge 8) \lor (P_{likely} \land R \ge 0.85) \lor (N_{b,1h} \ge 15)
$$

纯文本公式对照：
```text
quarantine_triggered = (block_count_5m >= 8) or (probe_likely and risk_score >= 0.85) or (block_count_1h >= 15)
```

* **变量释义对照**：
  * `Q` (`quarantine_triggered`)：布尔触发状态，为真时用户立即被持久化锁定入隔离区；
  * `N_{b,5m}` (`block_count_5m`)：5 分钟滑动窗口内累计被拦截次数（阈值为 8）；
  * `P_{likely}` (`probe_likely`)：审计联动标记的高置信度越权探测状态；
  * `R` (`risk_score`)：用户实时综合风险分；
  * `N_{b,1h}` (`block_count_1h`)：1 小时长周期内累计被拦截次数（阈值为 15）。

**隔离期行为语义**：
* 违规/越权操作：硬性阻断（`block`）；
* 合法操作：强制收紧降级为人工二次审批（`human_review`），剥夺智能体自主调用敏感工具权限；
* 管理员解封：支持调用 `POST /v1/quarantine/clear` 填写审核工单并解除用户隔离。

---

### 3.5 管理控制面双向联动与免重启热重载（Admin Control Plane）

1. **多租户三向身份对齐**：
   * 业务层用户标识 `user_id`（`usr_*`）、登录名 `username` 与 OpenClaw 专属智能体 `agent_id`（`agent_*`）三向强绑定；
   * 鉴权网关 `auth_gateway.py` 具备 `_lookup_db_user` 机制，未命中内存时动态回查 SQLite `auth.db`，确保零信任最小特权与身份防悬空。
2. **规则修改专属 Tab**：
   * OpenGuard 管理后台提供专属“规则修改”面板与全套 RESTful API；
   * 保存规则时同时完成 SQLite 数据库字段与文本规则文件的原子级写入；
   * Argus 引擎基于 `mtime` 文件监听在毫秒级内自动热重构内存规则树，业务零中断热生效。

---

## 四、 统一服务接口与数据契约

在工具调用前阶段（`stage = "tool_pre"`）由 Argus FastAPI 服务统一暴露：

### `POST /v1/tool/pre_check`

#### 4.1 请求格式 (`SecurityRequest`)
```json
{
  "context": {
    "trace_id": "trace-demo-001",
    "session_id": "session-001",
    "user_id": "user_01",
    "stage": "tool_pre",
    "timestamp": "2026-08-17T10:00:02Z"
  },
  "payload": {
    "tool_name": "read_file",
    "arguments": {
      "path": "C:\\Users\\admin\\Desktop\\notes.txt"
    },
    "database": ""
  }
}
```

#### 4.2 响应格式 (`ModuleResult`)

* **直接放行 (allow)**：
  ```json
  {
    "module": "access_control",
    "success": true,
    "action": "allow",
    "risk_score": 0.0,
    "reason": "allow: 用户等级 2 ≥ 资源所需 2",
    "details": {
      "user_id": "user_01",
      "tool": "tool:read_file",
      "path": "C:\\Users\\admin\\Desktop\\notes.txt"
    },
    "latency_ms": 0.42
  }
  ```

* **越权拦截 (block)**：
  ```json
  {
    "module": "access_control",
    "success": true,
    "action": "block",
    "risk_score": 1.0,
    "reason": "block: 用户等级 2 < 资源所需 4",
    "details": {
      "user_id": "user_01",
      "tool": "tool:exec",
      "path": ""
    },
    "latency_ms": 0.38
  }
  ```

* **二次审批 (human_review)**：
  ```json
  {
    "module": "access_control",
    "success": true,
    "action": "human_review",
    "risk_score": 0.65,
    "reason": "risk_escalated: 用户风险评分 0.65 ≥ 0.50，防线升级(penalty=1)后本应拦截，转人工审批(block_count=2)",
    "details": {
      "user_id": "user_01",
      "tool": "tool:read_file",
      "path": "C:\\Users\\admin\\Desktop\\notes.txt",
      "escalated": true,
      "penalty": 1
    },
    "latency_ms": 0.55
  }
  ```

---

## 五、 环境变量配置项

| 环境变量 | 默认值 | 可选值 / 说明 |
| :--- | :--- | :--- |
| `ARGUS_MODE` | `rbac` | `rbac`（角色访问控制）/ `mac`（强制标签）/ `hybrid`（双重校验） |
| `ARGUS_AC_RISK_LINK` | `1` | `1`（启用审计风险联动）/ `0`（禁用联动，回退纯静态判定） |
| `ARGUS_USERS_FILE` | 默认相对路径 | 自定义 `users.txt` 文件绝对路径 |
| `ARGUS_RESOURCES_FILE`| 默认相对路径 | 自定义 `resources.txt` 文件绝对路径 |
| `ARGUS_BLOCK_UNKNOWN_USERS`| `false` | 未注册用户是否直接硬拦截（为 `false` 时默认作为 1 级处理） |

---

## 六、 测试与验证

本模块拥有完备的单元测试与集成测试矩阵，使用以下命令执行全量验证：

```powershell
# 1. 运行访问控制与审计联动测试套件 (19 tests)
py -m pytest tests/test_access_control_risk_link.py

# 2. 运行访问控制基础单测套件 (32 tests)
py -m pytest tests/test_access_control.py

# 3. 运行 Argus 全量 100 项测试
py -m pytest tests/
```
