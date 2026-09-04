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

    def test_registration_creates_user_and_admin_can_see_it(self):
        response = self.client.post(
            "/register",
            data={"display_name": "Új Tesztelő", "email": "uj.tesztelo@example.hu", "password": "Teszt.123"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("A regisztráció elkészült".encode(), response.data)
        login_response = self.login("uj.tesztelo@example.hu", "Teszt.123")
        self.assertIn("Napi rögzítés".encode(), login_response.data)
        self.client.post("/logout")
        self.login("admin", "admin")
        admin_page = self.client.get("/admin/users")
        self.assertIn("uj.tesztelo@example.hu".encode(), admin_page.data)

    def test_registration_validation_is_visible_and_preserves_email(self):
        response = self.client.post(
            "/register",
            data={"display_name": "Teszt", "email": "hibas-email", "password": "123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("A fiók még nem jött létre".encode(), response.data)
        self.assertIn("Adj meg egy használható e-mail-címet".encode(), response.data)
        self.assertIn("A jelszó legalább 4 karakter legyen".encode(), response.data)
        self.assertIn(b'value="hibas-email"', response.data)

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

    def test_admin_edits_user_login_and_display_name(self):
        self.client.post(
            "/register",
            data={"display_name": "Régi Név", "email": "regi@example.hu", "password": "Teszt.123"},
        )
        with self.app.app_context():
            from worktime.db import get_db
            user_id = get_db().execute(
                "SELECT id FROM users WHERE login = 'regi@example.hu'"
            ).fetchone()["id"]

        self.login("admin", "admin")
        response = self.client.post(
            f"/admin/users/{user_id}/edit",
            data={"display_name": "Új Név", "login": "uj@example.hu"},
            follow_redirects=True,
        )
        self.assertIn("A felhasználó adatai frissültek".encode(), response.data)
        self.assertIn("uj@example.hu".encode(), response.data)
        self.assertIn("Új Név".encode(), response.data)

        self.client.post("/logout")
        login_response = self.login("uj@example.hu", "Teszt.123")
        self.assertIn("Napi rögzítés".encode(), login_response.data)

    def test_admin_rejects_duplicate_login(self):
        self.client.post(
            "/register",
            data={"display_name": "Másik", "email": "masik@example.hu", "password": "Teszt.123"},
        )
        with self.app.app_context():
            from worktime.db import get_db
            user_id = get_db().execute(
                "SELECT id FROM users WHERE login = 'masik@example.hu'"
            ).fetchone()["id"]

        self.login("admin", "admin")
        response = self.client.post(
            f"/admin/users/{user_id}/edit",
            data={"display_name": "Másik", "login": "admin"},
        )
        self.assertIn("Ez a felhasználónév már használatban van".encode(), response.data)

    def test_admin_deletes_user_and_all_related_data(self):
        self.client.post(
            "/register",
            data={"display_name": "Törlendő", "email": "torlendo@example.hu", "password": "Teszt.123"},
        )
        self.login("torlendo@example.hu", "Teszt.123")
        self.client.post(
            "/entry/save",
            data={
                "work_date": "2026-09-07",
                "arrival_time": "08:00:00",
                "departure_time": "18:00:00",
                "break_time": "00:00:00",
                "note": "törlési teszt",
            },
        )
        self.client.post("/leave", data={"year": "2026", "allowance": "25"})
        self.client.post("/logout")

        with self.app.app_context():
            from worktime.db import get_db
            user_id = get_db().execute(
                "SELECT id FROM users WHERE login = 'torlendo@example.hu'"
            ).fetchone()["id"]

        self.login("admin", "admin")
        response = self.client.post(
            f"/admin/users/{user_id}/delete", follow_redirects=True
        )
        self.assertIn("minden hozzá tartozó adat véglegesen törölve lett".encode(), response.data)
        with self.app.app_context():
            from worktime.db import get_db
            db = get_db()
            self.assertIsNone(db.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone())
            for table in ("work_schedules", "work_entries", "leave_allowances"):
                count = db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (user_id,)
                ).fetchone()[0]
                self.assertEqual(count, 0)

    def test_deleted_seed_user_is_not_recreated_on_restart(self):
        self.login("admin", "admin")
        with self.app.app_context():
            from worktime.db import get_db
            user_id = get_db().execute(
                "SELECT id FROM users WHERE login = 'sora.luna@gmail.com'"
            ).fetchone()["id"]
        self.client.post(f"/admin/users/{user_id}/delete")

        restarted_app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": self.db_path,
            "IMPORT_SEED_EXCEL": False,
        })
        with restarted_app.app_context():
            from worktime.db import get_db
            self.assertIsNone(
                get_db().execute(
                    "SELECT id FROM users WHERE login = 'sora.luna@gmail.com'"
                ).fetchone()
            )

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
