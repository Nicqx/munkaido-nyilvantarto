from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


SEED_META_KEY = "seed_excel_import_v1"
KNOWN_BAD_DATE = date(2026, 7, 27)


def as_date(value, epoch) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        converted = from_excel(value, epoch)
        return converted.date() if isinstance(converted, datetime) else converted
    return None


def as_seconds(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, datetime):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, timedelta):
        return max(0, int(round(value.total_seconds())))
    if isinstance(value, (int, float)):
        return max(0, int(round(float(value) * 86400)))
    return None


def seconds_to_clock(value: int | None) -> str | None:
    if value is None:
        return None
    return f"{value // 3600:02d}:{value % 3600 // 60:02d}:{value % 60:02d}"


def combined_note(name, column_k, column_l) -> str:
    parts = []
    for item in (column_k, column_l):
        text = str(item).strip() if item is not None else ""
        if text and text not in parts:
            parts.append(text)
    if name and "MNAP" in str(name).upper():
        parts.insert(0, str(name).strip())
    return " · ".join(parts)


def classify_day(name, note: str) -> str:
    folded = note.casefold()
    if "szabadság" in folded:
        return "leave_full"
    off_markers = ("húsvét", "ünnep", "pünkösd", "pn")
    if any(marker in folded for marker in off_markers) or "MNAP" in str(name or "").upper():
        return "off"
    return "work"


def import_seed_workbook(conn: sqlite3.Connection, user_id: int, workbook_path: str) -> dict:
    existing = conn.execute("SELECT value FROM app_meta WHERE key = ?", (SEED_META_KEY,)).fetchone()
    if existing:
        return json.loads(existing["value"])
    path = Path(workbook_path)
    if not path.exists():
        result = {"status": "missing", "path": str(path), "imported": 0}
        conn.execute("INSERT INTO app_meta(key, value) VALUES (?, ?)", (SEED_META_KEY, json.dumps(result)))
        return result

    workbook = load_workbook(path, data_only=True, read_only=True)
    imported = 0
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(min_row=4, values_only=True):
            name = row[0] if len(row) > 0 else None
            work_date = as_date(row[1] if len(row) > 1 else None, workbook.epoch)
            if work_date is None:
                continue
            arrival_seconds = as_seconds(row[2] if len(row) > 2 else None)
            departure_seconds = as_seconds(row[3] if len(row) > 3 else None)
            expected_seconds = as_seconds(row[5] if len(row) > 5 else None)
            note = combined_note(
                name,
                row[10] if len(row) > 10 else None,
                row[11] if len(row) > 11 else None,
            )
            day_type = classify_day(name, note)

            if work_date == KNOWN_BAD_DATE:
                arrival_seconds = None
                departure_seconds = None
                note = (note + " · " if note else "") + "Ellenőrzendő: az eredeti Excel képlete hibás volt"
            if day_type in ("leave_full", "off"):
                arrival_seconds = None
                departure_seconds = None
                expected_override = None
            else:
                expected_override = expected_seconds

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO work_entries(
                    user_id, work_date, arrival_time, departure_time, break_seconds,
                    break_started_at, day_type, expected_seconds_override, note,
                    source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, NULL, ?, ?, ?, 'excel-import', ?, ?)
                """,
                (
                    user_id,
                    work_date.isoformat(),
                    seconds_to_clock(arrival_seconds),
                    seconds_to_clock(departure_seconds),
                    day_type,
                    expected_override,
                    note,
                    now,
                    now,
                ),
            )
            if cursor.rowcount:
                imported += 1
            else:
                skipped += 1

    workbook.close()
    result = {
        "status": "ok",
        "file": path.name,
        "imported": imported,
        "skipped": skipped,
        "known_bad_date_left_empty": KNOWN_BAD_DATE.isoformat(),
    }
    conn.execute("INSERT INTO app_meta(key, value) VALUES (?, ?)", (SEED_META_KEY, json.dumps(result)))
    return result
