-- A task goal owns one room; deleting that room leaves a tombstone.
CREATE TABLE IF NOT EXISTS task_coordination_rooms (
  scope_id TEXT PRIMARY KEY REFERENCES task_coordination_scopes(scope_id) ON DELETE CASCADE,
  agent_id TEXT REFERENCES agents(agent_id) ON DELETE SET NULL,
  thread_id TEXT REFERENCES threads(thread_id) ON DELETE SET NULL,
  last_input_id TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_rooms_thread ON task_coordination_rooms(thread_id);
CREATE TABLE IF NOT EXISTS task_room_cursors (
  scope_id TEXT NOT NULL REFERENCES task_coordination_scopes(scope_id) ON DELETE CASCADE,
  source_thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
  last_seq INTEGER NOT NULL DEFAULT 0,
  source_kind TEXT NOT NULL DEFAULT 'projection',
  last_id TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(scope_id, source_thread_id)
);
CREATE TABLE IF NOT EXISTS task_room_inputs (
  scope_id TEXT NOT NULL REFERENCES task_coordination_scopes(scope_id) ON DELETE CASCADE,
  message_id TEXT NOT NULL,
  input_text TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY(scope_id, message_id)
);
CREATE TABLE IF NOT EXISTS task_room_sources (
  scope_id TEXT NOT NULL REFERENCES task_coordination_scopes(scope_id) ON DELETE CASCADE,
  thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
  caller_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
  parent_task_id TEXT REFERENCES agent_tasks(task_id) ON DELETE CASCADE,
  parent_attempt INTEGER,
  via_caller INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(scope_id, thread_id)
);
ALTER TABLE task_coordination_scopes ADD COLUMN peer_revision INTEGER NOT NULL DEFAULT 0;
UPDATE _schema_version SET version = 28;
