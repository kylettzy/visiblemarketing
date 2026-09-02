import gc
import tempfile
import unittest
from pathlib import Path

import app as application


class AdminCalendarTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = Path(self.temporary_directory.name) / "calendar.db"
        application.initialize_database()
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session.update(
                {
                    "admin_id": 1,
                    "admin_username": "calendar-admin",
                    "admin_role": "superadmin",
                    "csrf_token": "test-token",
                }
            )

    def tearDown(self):
        self.client = None
        application.DATABASE = self.original_database
        gc.collect()
        self.temporary_directory.cleanup()

    def test_calendar_page_renders(self):
        response = self.client.get("/admin/calendar?month=2026-09")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Project calendar", response.data)
        self.assertIn(b"September 2026", response.data)

    def test_created_event_appears_on_calendar(self):
        created = self.client.post(
            "/admin/calendar/events/new",
            data={
                "csrf_token": "test-token",
                "title": "Migration review",
                "starts_at": "2026-09-15T09:30",
                "location": "VTIC office",
                "notes": "Verify database persistence",
            },
        )

        self.assertEqual(created.status_code, 302)
        response = self.client.get("/admin/calendar?month=2026-09")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Migration review", response.data)


if __name__ == "__main__":
    unittest.main()
