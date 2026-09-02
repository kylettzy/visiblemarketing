import gc
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import app as application


class AccountManagementTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = Path(self.temporary_directory.name) / "accounts.db"
        application.initialize_database()
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session.update(
                {
                    "admin_id": 1,
                    "admin_username": "superadmin-test",
                    "admin_role": "superadmin",
                    "csrf_token": "test-token",
                    "credentials_verified_at": datetime.now(timezone.utc).timestamp(),
                }
            )

    def tearDown(self):
        self.client = None
        application.DATABASE = self.original_database
        gc.collect()
        self.temporary_directory.cleanup()

    def test_superadmin_can_create_and_edit_managed_accounts(self):
        self.assertEqual(self.client.get("/admin/accounts").status_code, 200)
        admin_response = self.client.post(
            "/admin/accounts/new/admin",
            data={
                "csrf_token": "test-token",
                "username": "managed-admin",
                "role": "admin",
                "password": "LongPassword123!",
                "confirm_password": "LongPassword123!",
            },
        )
        customer_response = self.client.post(
            "/admin/accounts/new/customer",
            data={
                "csrf_token": "test-token",
                "full_name": "Managed Customer",
                "email": "managed@example.com",
                "password": "LongPassword123!",
                "confirm_password": "LongPassword123!",
            },
        )
        self.assertEqual(admin_response.status_code, 302)
        self.assertEqual(customer_response.status_code, 302)

        with application.get_db() as database:
            admin = database.execute(
                "SELECT role FROM admins WHERE username = ?", ("managed-admin",)
            ).fetchone()
            customer = database.execute(
                "SELECT id FROM customers WHERE email = ?", ("managed@example.com",)
            ).fetchone()
        self.assertEqual(admin["role"], "admin")

        edit_response = self.client.post(
            f"/admin/accounts/customer/{customer['id']}/edit",
            data={
                "csrf_token": "test-token",
                "full_name": "Updated Customer",
                "email": "updated@example.com",
                "password": "",
                "confirm_password": "",
            },
        )
        self.assertEqual(edit_response.status_code, 302)
        with application.get_db() as database:
            updated = database.execute(
                "SELECT full_name FROM customers WHERE id = ?", (customer["id"],)
            ).fetchone()
        self.assertEqual(updated["full_name"], "Updated Customer")

    def test_regular_admin_cannot_manage_accounts(self):
        with self.client.session_transaction() as session:
            session["admin_role"] = "admin"
        self.assertEqual(self.client.get("/admin/accounts").status_code, 403)
        self.assertEqual(self.client.get("/admin/account/appearance").status_code, 200)
        self.assertEqual(self.client.get("/admin/account/database").status_code, 403)

    def test_superadmin_settings_navigation_exposes_account_sections(self):
        response = self.client.get("/admin/account")
        appearance = self.client.get("/admin/account/appearance")
        database = self.client.get("/admin/account/database")
        help_page = self.client.get("/admin/help")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(appearance.status_code, 200)
        self.assertEqual(database.status_code, 200)
        self.assertEqual(help_page.status_code, 200)
        self.assertIn(b"Complete a client review request", help_page.data)
        self.assertIn(b"Create an administrator or client account", help_page.data)
        self.assertIn(b'href="/admin/account"', response.data)
        self.assertIn(b'href="/admin/account/appearance"', response.data)
        self.assertIn(b'href="/admin/account/database"', response.data)
        self.assertIn(b'id="credentials"', response.data)
        self.assertNotIn(b'id="appearance"', response.data)
        self.assertNotIn(b'id="database"', response.data)
        self.assertIn(b'id="appearance"', appearance.data)
        self.assertNotIn(b'id="credentials"', appearance.data)
        self.assertIn(b'id="database"', database.data)
        self.assertNotIn(b'id="credentials"', database.data)

    def test_active_superadmin_cannot_demote_themselves(self):
        response = self.client.post(
            "/admin/accounts/admin/1/edit",
            data={
                "csrf_token": "test-token",
                "username": "superadmin-test",
                "role": "admin",
                "password": "",
                "confirm_password": "",
            },
            follow_redirects=True,
        )
        self.assertIn(
            b"cannot remove superadmin access from your active account",
            response.data,
        )

    def test_missing_managed_account_returns_to_directory(self):
        response = self.client.get(
            "/admin/accounts/admin/99999/edit", follow_redirects=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"That account is no longer available", response.data)
        self.assertIn(b"Users and administrators", response.data)


if __name__ == "__main__":
    unittest.main()
