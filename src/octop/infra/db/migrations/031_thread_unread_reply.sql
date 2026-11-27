BEGIN;
ALTER TABLE threads ADD COLUMN unread_reply_id TEXT;
UPDATE _schema_version SET version = 31;
COMMIT;
