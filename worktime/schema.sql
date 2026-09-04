PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_schedules (
    user_id INTEGER NOT NULL,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    expected_seconds INTEGER NOT NULL DEFAULT 0 CHECK (expected_seconds >= 0),
    PRIMARY KEY (user_id, weekday),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS work_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    work_date TEXT NOT NULL,
    arrival_time TEXT,
    departure_time TEXT,
    break_seconds INTEGER NOT NULL DEFAULT 0 CHECK (break_seconds >= 0),
    break_started_at TEXT,
    day_type TEXT NOT NULL DEFAULT 'work' CHECK (
        day_type IN ('work', 'leave_full', 'leave_half_am', 'leave_half_pm', 'off')
    ),
    expected_seconds_override INTEGER CHECK (expected_seconds_override >= 0),
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, work_date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS leave_allowances (
    user_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    allowance_half_days INTEGER NOT NULL DEFAULT 0 CHECK (allowance_half_days >= 0),
    PRIMARY KEY (user_id, year),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS calendar_overrides (
    work_date TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('holiday', 'rest_day', 'transferred_workday', 'normal')),
    source_date TEXT,
    label TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_user_date ON work_entries(user_id, work_date);
