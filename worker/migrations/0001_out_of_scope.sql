-- Migration 0001: add out_of_scope columns + relax NOT NULL on min_role_id
--
-- Step 1: add new columns to existing table
ALTER TABLE tasks ADD COLUMN out_of_scope TEXT DEFAULT NULL;
ALTER TABLE tasks ADD COLUMN out_of_scope_role TEXT DEFAULT NULL;

-- Step 2: clear task_search so we can drop tasks (FK dependency)
DELETE FROM task_search;

-- Step 3: recreate tasks with nullable min_role_id
CREATE TABLE tasks_new (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_area   TEXT NOT NULL,
  task_description TEXT NOT NULL,
  min_role_id    TEXT,              -- was NOT NULL; relaxed for out-of-scope tasks
  alt_role_ids   TEXT NOT NULL,
  notes          TEXT,
  source_url     TEXT,
  last_verified  TEXT NOT NULL,
  out_of_scope      TEXT DEFAULT NULL,
  out_of_scope_role TEXT DEFAULT NULL
);

INSERT INTO tasks_new
  SELECT id, feature_area, task_description, min_role_id,
         alt_role_ids, notes, source_url, last_verified,
         out_of_scope, out_of_scope_role
  FROM tasks;

DROP TABLE tasks;
ALTER TABLE tasks_new RENAME TO tasks;
