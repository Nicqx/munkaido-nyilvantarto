from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, g
from werkzeug.security import generate_password_hash

from .core import DEFAULT_SCHEDULE, default_schedule_times, ensure_calendar_year


SEED_USER_META_KEY = "seed_user_initialized_v1"
ADMIN_USER_META_KEY = "admin_user_initialized_v1"
SEED_IMPORT_META_KEY = "seed_excel_import_v1"


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
        arrival, departure = default_schedule_times(seconds)
        conn.execute(
            """
            INSERT OR IGNORE INTO work_schedules(
                user_id, weekday, expected_seconds,
                default_arrival_time, default_departure_time
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, weekday, seconds, arrival, departure),
        )


def migrate_schedule_defaults(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(work_schedules)").fetchall()
    }
    if "default_arrival_time" not in columns:
        conn.execute("ALTER TABLE work_schedules ADD COLUMN default_arrival_time TEXT")
    if "default_departure_time" not in columns:
        conn.execute("ALTER TABLE work_schedules ADD COLUMN default_departure_time TEXT")

    rows = conn.execute(
        """
        SELECT user_id, weekday, expected_seconds
        FROM work_schedules
        WHERE default_arrival_time IS NULL AND default_departure_time IS NULL
          AND expected_seconds > 0
        """
    ).fetchall()
    for row in rows:
        arrival, departure = default_schedule_times(row["expected_seconds"])
        conn.execute(
            """
            UPDATE work_schedules
            SET default_arrival_time = ?, default_departure_time = ?
            WHERE user_id = ? AND weekday = ?
            """,
            (arrival, departure, row["user_id"], row["weekday"]),
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
    migrate_schedule_defaults(conn)

    admin_user = conn.execute(
        "SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin_user:
        admin_password = app.config.get("ADMIN_PASSWORD", "")
        if not admin_password:
            conn.close()
            raise RuntimeError(
                "Első indítás előtt add meg az ADMIN_PASSWORD értékét a .env fájlban."
            )
        ensure_user(
            conn,
            app.config.get("ADMIN_LOGIN", "admin"),
            "Adminisztrátor",
            admin_password,
            is_admin=True,
        )
    conn.execute(
        "INSERT OR IGNORE INTO app_meta(key, value) VALUES (?, ?)",
        (ADMIN_USER_META_KEY, "1"),
    )

    already_imported = conn.execute(
        "SELECT 1 FROM app_meta WHERE key = ?", (SEED_IMPORT_META_KEY,)
    ).fetchone()
    seed_login = app.config.get("SEED_USER_LOGIN", "").strip()
    seed_password = app.config.get("SEED_USER_PASSWORD", "")
    seed_user = (
        conn.execute("SELECT id FROM users WHERE login = ?", (seed_login,)).fetchone()
        if seed_login
        else None
    )
    seed_user_id = int(seed_user["id"]) if seed_user else None
    seed_user_initialized = conn.execute(
        "SELECT 1 FROM app_meta WHERE key = ?", (SEED_USER_META_KEY,)
    ).fetchone()
    if not seed_user_initialized:
        should_create_seed = (
            not already_imported
            and (
                app.config.get("IMPORT_SEED_EXCEL", True)
                or bool(seed_login)
                or bool(seed_password)
            )
        )
        if should_create_seed and (not seed_login or not seed_password):
            conn.close()
            raise RuntimeError(
                "Az első Excel-import előtt add meg a SEED_USER_LOGIN és SEED_USER_PASSWORD értékét a .env fájlban."
            )
        if should_create_seed and seed_user_id is None:
            seed_user_id = ensure_user(
                conn,
                seed_login,
                app.config.get("SEED_USER_DISPLAY_NAME", "Importált felhasználó"),
                seed_password,
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
                if not seed_login or not seed_password:
                    conn.close()
                    raise RuntimeError(
                        "Az Excel-importhoz add meg a SEED_USER_LOGIN és SEED_USER_PASSWORD értékét a .env fájlban."
                    )
                seed_user_id = ensure_user(
                    conn,
                    seed_login,
                    app.config.get("SEED_USER_DISPLAY_NAME", "Importált felhasználó"),
                    seed_password,
                    is_admin=False,
                )
            import_seed_workbook(conn, seed_user_id, app.config["SEED_EXCEL_PATH"])
            conn.commit()
    conn.close()


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    init_database(app)
