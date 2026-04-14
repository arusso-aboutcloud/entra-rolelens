-- RoleLens D1 Schema
-- Apply with: wrangler d1 execute rolelens-db --file=worker/schema.sql

CREATE TABLE IF NOT EXISTS roles (
    id              TEXT PRIMARY KEY,           -- Entra role template GUID
    display_name    TEXT NOT NULL,
    description     TEXT,
    is_privileged   INTEGER NOT NULL DEFAULT 0, -- 1 = true (D1 has no BOOLEAN)
    is_built_in     INTEGER NOT NULL DEFAULT 1,
    permissions     TEXT NOT NULL DEFAULT '[]', -- JSON array of allowedResourceActions
    first_seen      TEXT NOT NULL,              -- ISO-8601
    last_updated    TEXT NOT NULL               -- ISO-8601
);

CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_area    TEXT NOT NULL,              -- e.g. "Authentication", "Conditional Access"
    task_description TEXT NOT NULL,
    min_role_id     TEXT NOT NULL REFERENCES roles(id),
    alt_role_ids    TEXT NOT NULL DEFAULT '[]', -- JSON array of role GUIDs
    notes           TEXT,
    source_url      TEXT,
    last_verified   TEXT NOT NULL               -- ISO-8601
);

CREATE TABLE IF NOT EXISTS role_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    change_date     TEXT NOT NULL,              -- ISO-8601
    change_type     TEXT NOT NULL,              -- 'added' | 'removed' | 'modified'
    role_id         TEXT NOT NULL,
    role_name       TEXT NOT NULL,
    field_changed   TEXT,                       -- null for added/removed roles
    old_value       TEXT,
    new_value       TEXT
);

-- FTS-lite: pre-tokenised keyword table used by the search engine
CREATE TABLE IF NOT EXISTS task_search (
    task_id         INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    keyword         TEXT NOT NULL,
    weight          REAL NOT NULL DEFAULT 1.0,  -- higher = more relevant
    PRIMARY KEY (task_id, keyword)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_roles_display_name   ON roles(display_name);
CREATE INDEX IF NOT EXISTS idx_tasks_feature_area   ON tasks(feature_area);
CREATE INDEX IF NOT EXISTS idx_tasks_min_role        ON tasks(min_role_id);
CREATE INDEX IF NOT EXISTS idx_role_changes_date     ON role_changes(change_date DESC);
CREATE INDEX IF NOT EXISTS idx_role_changes_role_id  ON role_changes(role_id);
CREATE INDEX IF NOT EXISTS idx_task_search_keyword   ON task_search(keyword);
