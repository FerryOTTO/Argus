-- ============================================================================
-- 011: 用户安全等级（Argus access_control 身份方案）
-- 背景：原生 OpenClaw 迁移后，聊天身份改由 LLMGate 统一存发。
--       users 表新增 security_level + specials，与
--       Argus/argus/modules/access_control/original/rules/users.txt
--       第三列写法对齐（逗号分隔，如 *,!tool:write_file）。
-- 1) security_level 取值 public/internal/secret/top_secret，
--    与 auth_gateway._normalize_level 完全对齐，默认 internal；
-- 2) specials 原样透传，终端写入本地规则时零转换；
-- 3) must_change_password 已在 005 加过，这里不再加。
-- ============================================================================

ALTER TABLE users ADD COLUMN security_level TEXT NOT NULL DEFAULT 'internal';
ALTER TABLE users ADD COLUMN specials TEXT NOT NULL DEFAULT '';
