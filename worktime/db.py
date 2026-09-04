from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

from .core import DEFAULT_SCHEDULE, ensure_calendar_year


SEED_USER_META_KEY = "seed_user_initialized_v1"


def connect_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect_db(current_app.config["DATABASE"])
    return g.db


def close_db(_error=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def add_default_schedule(conn: sqlite3.Connection, user_id: int) -> None:
    for weekday, seconds in DEFAULT_SCHEDULE.items():
        conn.execute(
            "INSERT OR IGNORE INTO work_schedules(user_id, weekday, expected_seconds) VALUES (?, ?, ?)",
            (user_id, weekday, seconds),
        )


def ensure_user(
    conn: sqlite3.Connection,
    login: str,
    display_name: str,
    password: str,
    *,
    is_admin: bool = False,
) -> int:
    existing = conn.execute("SELECT id FROM users WHERE login = ?", (login,)).fetchone()
    if existing:
        add_default_schedule(conn, existing["id"])
        return int(existing["id"])
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        """
        INSERT INTO users(login, display_name, password_hash, is_admin, active, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (login, display_name, generate_password_hash(password), int(is_admin), now),
    )
    user_id = int(cursor.lastrowid)
    add_default_schedule(conn, user_id)
    return user_id


def init_database(app) -> None:
    path = app.config["DATABASE"]
    conn = connect_db(path)
    schema_path = Path(__file__).with_name("schema.sql")
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    ensure_user(conn, "admin", "Adminisztrátor", "admin", is_admin=True)
    seed_user = conn.execute(
        "SELECT id FROM users WHERE login = ?", ("sora.luna@gmail.com",)
    ).fetchone()
    seed_user_id = int(seed_user["id"]) if seed_user else None
    seed_user_initialized = conn.execute(
        "SELECT 1 FROM app_meta WHERE key = ?", (SEED_USER_META_KEY,)
    ).fetchone()
    if not seed_user_initialized:
        if seed_user_id is None:
            seed_user_id = ensure_user(
                conn,
                "sora.luna@gmail.com",
                "Kovács Anna",
                "Almafa.123",
                is_admin=False,
            )
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES (?, ?)",
            (SEED_USER_META_KEY, "1"),
        )
    ensure_calendar_year(conn, datetime.now().year)
    ensure_calendar_year(conn, 2026)
    conn.commit()

    if app.config.get("IMPORT_SEED_EXCEL", True):
        from .importer import SEED_META_KEY, import_seed_workbook

        already_imported = conn.execute(
            "SELECT 1 FROM app_meta WHERE key = ?", (SEED_META_KEY,)
        ).fetchone()
        if not already_imported:
            if seed_user_id is None:
                seed_user_id = ensure_user(
                    conn,
                    "sora.luna@gmail.com",
                    "Kovács Anna",
                    "Almafa.123",
                    is_admin=False,
                )
            import_seed_workbook(conn, seed_user_id, app.config["SEED_EXCEL_PATH"])
            conn.commit()
    conn.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    init_database(app)
