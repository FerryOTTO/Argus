-- ============================================================================
-- 009: 终端 Argus 审计事件汇聚（审计日志 · 终端审计板块）
-- 背景：终端侧 Argus 审计层（本地 JSONL AuditEvent）按周期批量上报，
--       集控端落库汇聚，供控制台"审计日志"板块浏览/筛选/导出。
-- 1) agent_audit_events：一条 = 一个 AuditEvent；以 (terminal_id, event_id)
--    幂等去重（客户端重传不产生重复行）；
-- 2) event_time 落库为 UTC RFC3339 秒级定宽文本（如 2026-09-08T10:00:00Z），
--    文本序 = 时间序，可直接做区间与排序；
-- 3) terminal_name 为上报时刻快照：终端随后删除/改名不影响历史审计展示；
-- 4) 不设外键：终端记录删除后审计事件保留（审计不随被审计对象销毁）。
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    terminal_id INTEGER NOT NULL,
    terminal_name TEXT NOT NULL DEFAULT '',
    event_id TEXT NOT NULL,
    trace_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    event_time TEXT NOT NULL,
    stage TEXT NOT NULL,
    source_module TEXT NOT NULL,
    action TEXT NOT NULL,
    risk_score REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (terminal_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_audit_events_time ON agent_audit_events(event_time);
CREATE INDEX IF NOT EXISTS idx_agent_audit_events_terminal_time ON agent_audit_events(terminal_id, event_time);
CREATE INDEX IF NOT EXISTS idx_agent_audit_events_stage ON agent_audit_events(stage);
CREATE INDEX IF NOT EXISTS idx_agent_audit_events_action ON agent_audit_events(action);
CREATE INDEX IF NOT EXISTS idx_agent_audit_events_module ON agent_audit_events(source_module);
CREATE INDEX IF NOT EXISTS idx_agent_audit_events_risk ON agent_audit_events(risk_score);
