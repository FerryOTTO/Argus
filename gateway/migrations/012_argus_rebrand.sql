-- 012: 品牌统一（ClawGuard -> Argus）后的历史列改名。
--
-- 背景：007_terminals.sql 建表时的列名是 `clawguard_version`。已经跑过 007 的库
-- 不会重跑该文件（schema_migrations 已记录），所以不能直接改 007 的列名，
-- 否则老库会停留在旧列名、新代码查 `argus_version` 时报 no such column。
--
-- 这里按「加新列 -> 搬运数据 -> 删旧列」三步改名，对新库（刚由 007 建出旧列）
-- 与老库（早已存在旧列）结果一致，且只会执行一次。
ALTER TABLE agent_terminals ADD COLUMN argus_version TEXT NOT NULL DEFAULT '';
UPDATE agent_terminals SET argus_version = clawguard_version;
ALTER TABLE agent_terminals DROP COLUMN clawguard_version;
