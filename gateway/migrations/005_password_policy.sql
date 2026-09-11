ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0;
UPDATE users SET must_change_password = 1 WHERE username = 'admin';
