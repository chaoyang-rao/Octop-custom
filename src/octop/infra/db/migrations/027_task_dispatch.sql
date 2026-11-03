-- One-to-one task delivery context; existing task history and options stay intact.
CREATE TABLE IF NOT EXISTS task_coordination_scopes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope_id TEXT NOT NULL UNIQUE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  origin_agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
  origin_thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
  parent_task_id TEXT REFERENCES agent_tasks(task_id) ON DELETE SET NULL,
  parent_attempt INTEGER,
  source_message_id TEXT NOT NULL,
  goal_text TEXT NOT NULL,
  allow_publish INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','idle','needs_user','interrupted','stopped')),
  last_signature TEXT NOT NULL DEFAULT '',
  active_signature TEXT NOT NULL DEFAULT '',
  review_turns INTEGER NOT NULL DEFAULT 0,
  decision TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  question TEXT NOT NULL DEFAULT '',
  user_input TEXT NOT NULL DEFAULT '',
  resume_seq INTEGER NOT NULL DEFAULT 0,
  handled_resume_seq INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_dispatch_context (
  task_id TEXT PRIMARY KEY REFERENCES agent_tasks(task_id) ON DELETE CASCADE,
  origin_agent_id TEXT REFERENCES agents(agent_id) ON DELETE SET NULL,
  origin_thread_id TEXT REFERENCES threads(thread_id) ON DELETE SET NULL,
  request_key TEXT UNIQUE,
  parent_task_id TEXT REFERENCES agent_tasks(task_id) ON DELETE SET NULL,
  parent_attempt INTEGER,
  scope_id TEXT REFERENCES task_coordination_scopes(scope_id) ON DELETE SET NULL,
  coding_spec_json TEXT,
  coding_run_json TEXT NOT NULL DEFAULT '{}',
  returned_attempt INTEGER NOT NULL DEFAULT 0,
  returned_state TEXT NOT NULL DEFAULT '',
  returned_event_id INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_task_dispatch_origin ON task_dispatch_context(origin_thread_id);
CREATE INDEX IF NOT EXISTS idx_task_dispatch_parent ON task_dispatch_context(parent_task_id,parent_attempt);
CREATE INDEX IF NOT EXISTS idx_task_dispatch_scope ON task_dispatch_context(scope_id);
CREATE INDEX IF NOT EXISTS idx_task_coordination_parent ON task_coordination_scopes(parent_task_id,parent_attempt);
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id,id);

UPDATE _schema_version SET version = 27;
