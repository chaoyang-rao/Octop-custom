-- Local customization: project folders organize an expert's conversations.
ALTER TABLE threads ADD COLUMN project_path TEXT;
ALTER TABLE threads ADD COLUMN project_name TEXT;
CREATE TABLE IF NOT EXISTS thread_projects (
  agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_path TEXT NOT NULL,
  project_name TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY(agent_id, user_id, project_path)
);
CREATE INDEX IF NOT EXISTS idx_threads_project ON threads(agent_id, user_id, project_path);
UPDATE _schema_version SET version = 22;
