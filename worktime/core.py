from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable


DEFAULT_SCHEDULE = {
    0: 10 * 3600,
    1: 8 * 3600,
    2: 8 * 3600 + 30 * 60,
    3: 8 * 3600,
    4: 5 * 3600 + 30 * 60,
    5: 0,
    6: 0,
}
DEFAULT_ARRIVAL_SECONDS = 8 * 3600

DAY_NAMES = ["Hétfő", "Kedd", "Szerda", "Csütörtök", "Péntek", "Szombat", "Vasárnap"]
MONTH_NAMES = [
    "", "Január", "Február", "Március", "Április", "Május", "Június",
    "Július", "Augusztus", "Szeptember", "Október", "November", "December",
]

DAY_TYPE_LABELS = {
    "work": "Munkanap",
    "leave_full": "Szabadság",
    "leave_half_am": "Fél nap szabadság – délelőtt",
    "leave_half_pm": "Fél nap szabadság – délután",
    "off": "Nem számolt nap",
}


def parse_hms(value: str | None, *, allow_over_24: bool = False) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("Az idő formátuma ÓÓ:PP vagy ÓÓ:PP:MM legyen.")
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as exc:
        raise ValueError("Az idő csak számokat tartalmazhat.") from exc
    max_hours = 999 if allow_over_24 else 23
    if not (0 <= hours <= max_hours and 0 <= minutes <= 59 and 0 <= seconds <= 59):
        raise ValueError("Érvénytelen időérték.")
    return hours * 3600 + minutes * 60 + seconds


def format_clock(value: int | None) -> str:
    if value is None:
        return ""
    value = max(0, int(value))
    return f"{value // 3600:02d}:{value % 3600 // 60:02d}:{value % 60:02d}"


def format_duration(value: int | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    value = int(round(value))
    sign = ""
    if signed:
        sign = "+" if value >= 0 else "−"
    elif value < 0:
        sign = "−"
    absolute = abs(value)
    return f"{sign}{absolute // 3600:02d}:{absolute % 3600 // 60:02d}:{absolute % 60:02d}"


def clock_now_text(local_now: datetime) -> str:
    return local_now.strftime("%H:%M:%S")


def easter_sunday(year: int) -> date:
    """Gregorian Easter date, Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def holiday_rows(year: int) -> list[tuple[str, str, str | None, str]]:
    easter = easter_sunday(year)
    rows = [
        (date(year, 1, 1).isoformat(), "holiday", None, "Újév"),
        (date(year, 3, 15).isoformat(), "holiday", None, "Nemzeti ünnep"),
        ((easter - timedelta(days=2)).isoformat(), "holiday", None, "Nagypéntek"),
        ((easter + timedelta(days=1)).isoformat(), "holiday", None, "Húsvéthétfő"),
        (date(year, 5, 1).isoformat(), "holiday", None, "A munka ünnepe"),
        ((easter + timedelta(days=50)).isoformat(), "holiday", None, "Pünkösdhétfő"),
        (date(year, 8, 20).isoformat(), "holiday", None, "Az államalapítás ünnepe"),
        (date(year, 10, 23).isoformat(), "holiday", None, "Nemzeti ünnep"),
        (date(year, 11, 1).isoformat(), "holiday", None, "Mindenszentek"),
        (date(year, 12, 25).isoformat(), "holiday", None, "Karácsony"),
        (date(year, 12, 26).isoformat(), "holiday", None, "Karácsony másnapja"),
    ]
    if year == 2026:
        rows.extend([
            ("2026-01-02", "rest_day", None, "Áthelyezett pihenőnap"),
            ("2026-01-10", "transferred_workday", "2026-01-02", "Január 2. ledolgozása"),
            ("2026-08-21", "rest_day", None, "Áthelyezett pihenőnap"),
            ("2026-08-08", "transferred_workday", "2026-08-21", "Augusztus 21. ledolgozása"),
            ("2026-12-24", "rest_day", None, "Áthelyezett pihenőnap"),
            ("2026-12-12", "transferred_workday", "2026-12-24", "December 24. ledolgozása"),
        ])
    return rows


def ensure_calendar_year(conn: sqlite3.Connection, year: int) -> None:
    for row in holiday_rows(year):
        conn.execute(
            """
            INSERT OR IGNORE INTO calendar_overrides(work_date, kind, source_date, label)
            VALUES (?, ?, ?, ?)
            """,
            row,
        )


def schedule_seconds(conn: sqlite3.Connection, user_id: int, weekday: int) -> int:
    return schedule_details(conn, user_id, weekday)[0]


def default_schedule_times(expected_seconds: int) -> tuple[str | None, str | None]:
    expected_seconds = max(0, int(expected_seconds))
    if expected_seconds == 0:
        return None, None
    start = DEFAULT_ARRIVAL_SECONDS
    if start + expected_seconds >= 24 * 3600:
        start = 0
    departure = start + expected_seconds
    if departure >= 24 * 3600:
        return None, None
    return format_clock(start), format_clock(departure)


def schedule_details(
    conn: sqlite3.Connection, user_id: int, weekday: int
) -> tuple[int, str | None, str | None]:
    row = conn.execute(
        """
        SELECT expected_seconds, default_arrival_time, default_departure_time
        FROM work_schedules WHERE user_id = ? AND weekday = ?
        """,
        (user_id, weekday),
    ).fetchone()
    if row:
        return (
            int(row["expected_seconds"]),
            row["default_arrival_time"],
            row["default_departure_time"],
        )
    expected = DEFAULT_SCHEDULE[weekday]
    arrival, departure = default_schedule_times(expected)
    return expected, arrival, departure


def calendar_schedule_details(
    conn: sqlite3.Connection, user_id: int, day: date
) -> tuple[int, str | None, str | None, str]:
    ensure_calendar_year(conn, day.year)
    override = conn.execute(
        "SELECT kind, source_date, label FROM calendar_overrides WHERE work_date = ?",
        (day.isoformat(),),
    ).fetchone()
    if override:
        if override["kind"] in ("holiday", "rest_day"):
            return 0, None, None, override["label"]
        if override["kind"] == "transferred_workday":
            source = date.fromisoformat(override["source_date"])
            expected, arrival, departure = schedule_details(conn, user_id, source.weekday())
            return expected, arrival, departure, override["label"]
        # A stored "normal" value deliberately overrides a built-in holiday.
    expected, arrival, departure = schedule_details(conn, user_id, day.weekday())
    label = "Hétvége" if day.weekday() >= 5 and expected == 0 else ""
    return expected, arrival, departure, label


def calendar_expected_seconds(conn: sqlite3.Connection, user_id: int, day: date) -> tuple[int, str]:
    expected, _arrival, _departure, label = calendar_schedule_details(conn, user_id, day)
    return expected, label


def expected_seconds_for_entry(
    conn: sqlite3.Connection,
    user_id: int,
    day: date,
    entry: sqlite3.Row | dict | None,
) -> tuple[int | None, str]:
    if entry and entry["day_type"] in ("leave_full", "off"):
        return None, DAY_TYPE_LABELS[entry["day_type"]]
    if entry and entry["expected_seconds_override"] is not None:
        base = int(entry["expected_seconds_override"])
        label = "Egyedi/importált munkaidő"
    else:
        base, label = calendar_expected_seconds(conn, user_id, day)
    if entry and entry["day_type"] in ("leave_half_am", "leave_half_pm"):
        return base // 2, DAY_TYPE_LABELS[entry["day_type"]]
    return base, label


@dataclass
class EntryMetrics:
    complete: bool
    included: bool
    worked_seconds: int | None
    expected_seconds: int | None
    balance_seconds: int | None
    gross_seconds: int | None
    calendar_label: str


def entry_metrics(
    conn: sqlite3.Connection,
    user_id: int,
    day: date,
    entry: sqlite3.Row | dict | None,
) -> EntryMetrics:
    expected, label = expected_seconds_for_entry(conn, user_id, day, entry)
    if not entry or entry["day_type"] in ("leave_full", "off"):
        return EntryMetrics(False, False, None, expected, None, None, label)
    arrival = parse_hms(entry["arrival_time"])
    departure = parse_hms(entry["departure_time"])
    if arrival is None or departure is None:
        return EntryMetrics(False, False, None, expected, None, None, label)
    if departure < arrival:
        return EntryMetrics(False, False, None, expected, None, None, label)
    gross = departure - arrival
    worked = max(0, gross - int(entry["break_seconds"] or 0))
    return EntryMetrics(True, True, worked, expected, worked - int(expected or 0), gross, label)


def iter_month_days(year: int, month: int) -> Iterable[date]:
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        yield date(year, month, day)


def month_shift(year: int, month: int, offset: int) -> tuple[int, int]:
    absolute = year * 12 + (month - 1) + offset
    return absolute // 12, absolute % 12 + 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
