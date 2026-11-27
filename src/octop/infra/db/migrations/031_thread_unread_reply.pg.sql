ALTER TABLE IF EXISTS threads ADD COLUMN IF NOT EXISTS unread_reply_id TEXT;
UPDATE _schema_version SET version = 31;
