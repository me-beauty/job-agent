-- Job Agent 数据库建表 DDL (SQLite)
-- 首次运行自动创建

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL DEFAULT 'unknown',  -- csv / md / jobhunt / websearch / browser
    title       TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    description TEXT DEFAULT '',
    location    TEXT DEFAULT '',
    salary      TEXT DEFAULT '',
    url         TEXT DEFAULT '',
    keywords    TEXT DEFAULT '',                   -- comma-separated
    match_score REAL DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL UNIQUE,              -- external task id
    type        TEXT NOT NULL DEFAULT 'unknown',   -- search / apply / scrape / train
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending / running / done / error
    params      TEXT DEFAULT '{}',                 -- JSON
    result      TEXT DEFAULT '{}',                 -- JSON
    error_msg   TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now','localtime')),
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS apply_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER DEFAULT 0,
    job_url     TEXT NOT NULL DEFAULT '',
    resume_path TEXT DEFAULT '',
    match_score REAL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'skipped',   -- skipped / attempted / success / failed
    error_msg   TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS models (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,              -- e.g. job_match_v001
    path        TEXT NOT NULL,                     -- full path to .pt file
    epochs      INTEGER DEFAULT 30,
    val_mae     REAL DEFAULT 0,
    val_loss    REAL DEFAULT 0,
    accuracy    REAL DEFAULT 0,
    is_active   INTEGER DEFAULT 0,
    eval_report TEXT DEFAULT '',                   -- JSON path
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- MCP 工具调用持久化日志 (v3.1)
CREATE TABLE IF NOT EXISTS tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     TEXT NOT NULL UNIQUE,              -- hash(tool_name + params + timestamp)
    tool_name   TEXT NOT NULL DEFAULT '',
    params      TEXT DEFAULT '{}',                 -- JSON
    result      TEXT DEFAULT '',                   -- truncated result
    duration_ms REAL DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'success',   -- success / failed / cached
    error_msg   TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- 样本监控快照 (v3.1)
CREATE TABLE IF NOT EXISTS sample_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    total_count INTEGER DEFAULT 0,
    bin_0_20    INTEGER DEFAULT 0,
    bin_20_40   INTEGER DEFAULT 0,
    bin_40_60   INTEGER DEFAULT 0,
    bin_60_80   INTEGER DEFAULT 0,
    bin_80_100  INTEGER DEFAULT 0,
    source_breakdown TEXT DEFAULT '{}',            -- JSON
    snapshot_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_source     ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_created    ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_type      ON tasks(type);
CREATE INDEX IF NOT EXISTS idx_tasks_status    ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_apply_logs_job  ON apply_logs(job_id);
CREATE INDEX IF NOT EXISTS idx_models_active   ON models(is_active);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_time ON tool_calls(created_at);
