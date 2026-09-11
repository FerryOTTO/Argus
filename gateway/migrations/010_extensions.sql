-- Extension Governance: skill/MCP 安装审批 + Skill 分发（契约见 CLIENT.md，包规范见 SKILL_CREATION.md）
-- 1) 安装审批单：终端要安装新 skill / 接入新 MCP 时上报，管理员（或预留的自动决策器）审批后客户端才执行安装
CREATE TABLE IF NOT EXISTS extension_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    terminal_id INTEGER NOT NULL,
    -- 终端名快照：终端删除/改名后审批记录仍可读
    terminal_name TEXT NOT NULL DEFAULT '',
    -- 申请类型: skill（安装技能）| mcp（接入 MCP 服务）
    kind TEXT NOT NULL CHECK (kind IN ('skill', 'mcp')),
    -- 展示名：skill 名 / MCP server 名
    name TEXT NOT NULL,
    -- 来源说明（目录/市场/手工等，客户端自由文本）
    source TEXT NOT NULL DEFAULT '',
    -- 申请明细 JSON 对象（skill: 内容摘要或来源标识；mcp: server 定义）；≤64KB
    payload TEXT NOT NULL DEFAULT '{}',
    -- 终端提交的申请理由
    reason TEXT NOT NULL DEFAULT '',
    -- 状态机: pending（待审批）| approved（放行，客户端可安装）| rejected（驳回）
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'approved', 'rejected')),
    -- 审批方式: manual（人工）| auto（自动决策器，初期预留）
    approve_mode TEXT NOT NULL DEFAULT 'manual' CHECK (approve_mode IN ('manual', 'auto')),
    reviewer_id INTEGER,
    review_note TEXT NOT NULL DEFAULT '',
    reviewed_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY (terminal_id) REFERENCES agent_terminals(id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_id) REFERENCES users(id)
);
CREATE INDEX idx_ext_approvals_state ON extension_approvals(state, created_at);
CREATE INDEX idx_ext_approvals_terminal ON extension_approvals(terminal_id, created_at);

-- 2) Skill 分发包：zip 原样存储（OpenClaw 适配格式，见 SKILL_CREATION.md）；同名重新上传 = 版本 +1，
--    既有分配保留，终端凭版本差重新拉取
CREATE TABLE IF NOT EXISTS skill_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- skill 标识 = zip 内顶层目录名（^[A-Za-z0-9][A-Za-z0-9_-]*$，唯一）
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    zip_name TEXT NOT NULL DEFAULT '',
    zip_size INTEGER NOT NULL DEFAULT 0,
    zip_data BLOB NOT NULL,
    -- SKILL.md 正文摘要（上传时截取前 4000 字符，列表/详情展示，不随分发下传）
    preview TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    FOREIGN KEY (created_by) REFERENCES users(id)
);

-- 3) 包 → 终端分配（全量覆盖语义由管理端 handler 维护）
CREATE TABLE IF NOT EXISTS skill_package_assignments (
    package_id INTEGER NOT NULL,
    terminal_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (package_id, terminal_id),
    FOREIGN KEY (package_id) REFERENCES skill_packages(id) ON DELETE CASCADE,
    FOREIGN KEY (terminal_id) REFERENCES agent_terminals(id) ON DELETE CASCADE
);
CREATE INDEX idx_skill_assign_terminal ON skill_package_assignments(terminal_id);

-- 4) 终端安装回执（每终端每包保留最新一条；package_version < 包当前版本 ⇒ 待同步重拉）
CREATE TABLE IF NOT EXISTS skill_package_applyments (
    package_id INTEGER NOT NULL,
    terminal_id INTEGER NOT NULL,
    package_version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'failed')),
    message TEXT NOT NULL DEFAULT '',
    applied_at DATETIME NOT NULL,
    PRIMARY KEY (package_id, terminal_id),
    FOREIGN KEY (package_id) REFERENCES skill_packages(id) ON DELETE CASCADE,
    FOREIGN KEY (terminal_id) REFERENCES agent_terminals(id) ON DELETE CASCADE
);
