import os
import tempfile
import unittest

from openpyxl import load_workbook

from worktime import create_app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": self.db_path,
            "IMPORT_SEED_EXCEL": False,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def login(self, login="sora.luna@gmail.com", password="Almafa.123"):
        return self.client.post("/login", data={"login": login, "password": password}, follow_redirects=True)

    def test_seed_accounts_can_log_in(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Napi rögzítés".encode(), response.data)

    def test_complete_day_and_break_are_calculated(self):
        self.login()
        response = self.client.post(
            "/entry/save",
            data={
                "work_date": "2026-09-07",
                "arrival_time": "08:00:00",
                "departure_time": "18:00:00",
                "break_time": "00:15:00",
                "note": "teszt",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("09:45:00".encode(), response.data)
        self.assertIn("−00:15:00".encode(), response.data)

    def test_full_leave_consumes_one_day(self):
        self.login()
        self.client.post("/leave", data={"year": "2026", "allowance": "25"})
        self.client.post("/entry/leave", data={"work_date": "2026-09-08", "kind": "leave_full"})
        response = self.client.get("/leave?year=2026")
        self.assertIn("24.0 nap".encode(), response.data)

    def test_admin_resets_password(self):
        self.login("admin", "admin")
        with self.app.app_context():
            from worktime.db import get_db
            user = get_db().execute("SELECT id FROM users WHERE login = 'sora.luna@gmail.com'").fetchone()
            user_id = user["id"]
        response = self.client.post(f"/admin/users/{user_id}/reset-password", follow_redirects=True)
        self.assertIn("Almafa.123".encode(), response.data)

    def test_excel_export_is_valid(self):
        self.login()
        response = self.client.get("/export.xlsx?year=2026")
        self.assertEqual(response.status_code, 200)
        target = os.path.join(self.tmp.name, "export.xlsx")
        with open(target, "wb") as handle:
            handle.write(response.data)
        workbook = load_workbook(target, read_only=True)
        self.assertEqual(workbook.sheetnames, ["Munkaidőadatok", "Havi összesítő", "Éves összesítő", "Információ"])
        workbook.close()


if __name__ == "__main__":
    unittest.main()
