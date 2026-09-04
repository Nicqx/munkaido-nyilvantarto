import sqlite3
import unittest
from datetime import date

from worktime.core import DEFAULT_SCHEDULE, entry_metrics, format_duration, parse_hms


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE users(id INTEGER PRIMARY KEY);
            CREATE TABLE work_schedules(user_id INTEGER, weekday INTEGER, expected_seconds INTEGER, PRIMARY KEY(user_id, weekday));
            CREATE TABLE calendar_overrides(work_date TEXT PRIMARY KEY, kind TEXT, source_date TEXT, label TEXT);
            INSERT INTO users(id) VALUES (1);
            """
        )
        self.conn.executemany(
            "INSERT INTO work_schedules(user_id, weekday, expected_seconds) VALUES (1, ?, ?)",
            DEFAULT_SCHEDULE.items(),
        )

    def tearDown(self):
        self.conn.close()

    def test_time_parsing_and_formatting(self):
        self.assertEqual(parse_hms("08:12:34"), 8 * 3600 + 12 * 60 + 34)
        self.assertEqual(format_duration(-3670, signed=True), "−01:01:10")

    def test_break_reduces_worked_time(self):
        entry = {
            "arrival_time": "08:00:00",
            "departure_time": "18:00:00",
            "break_seconds": 15 * 60,
            "day_type": "work",
            "expected_seconds_override": None,
        }
        result = entry_metrics(self.conn, 1, date(2026, 9, 7), entry)
        self.assertEqual(result.worked_seconds, 9 * 3600 + 45 * 60)
        self.assertEqual(result.balance_seconds, -15 * 60)

    def test_half_day_uses_half_of_planned_hours(self):
        entry = {
            "arrival_time": "08:00:00",
            "departure_time": "13:15:00",
            "break_seconds": 0,
            "day_type": "leave_half_am",
            "expected_seconds_override": None,
        }
        result = entry_metrics(self.conn, 1, date(2026, 9, 7), entry)
        self.assertEqual(result.expected_seconds, 5 * 3600)
        self.assertEqual(result.balance_seconds, 15 * 60)

    def test_transferred_saturday_inherits_original_weekday(self):
        self.conn.execute(
            "INSERT INTO calendar_overrides VALUES ('2026-08-08', 'transferred_workday', '2026-08-21', 'Áthelyezés')"
        )
        entry = {
            "arrival_time": "08:00:00",
            "departure_time": "13:30:00",
            "break_seconds": 0,
            "day_type": "work",
            "expected_seconds_override": None,
        }
        result = entry_metrics(self.conn, 1, date(2026, 8, 8), entry)
        self.assertEqual(result.expected_seconds, 5 * 3600 + 30 * 60)
        self.assertEqual(result.balance_seconds, 0)


if __name__ == "__main__":
    unittest.main()
