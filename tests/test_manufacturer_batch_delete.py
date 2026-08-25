import gc
import tempfile
import unittest
from pathlib import Path

import app as application


class ManufacturerBatchDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = Path(self.temporary_directory.name) / "batch-delete.db"
        application.initialize_database()

        with application.get_db() as database:
            manufacturer_id = database.execute(
                "INSERT INTO manufacturers (name) VALUES ('Batch Test')"
            ).lastrowid
            database.execute("INSERT INTO manufacturers (name) VALUES ('Other Test')")
            database.executemany(
                """INSERT INTO products
                   (brand, name, category, description, source)
                   VALUES (?, ?, 'Switches', 'Test product', 'Test')""",
                [
                    ("Batch Test", "Delete One"),
                    ("Batch Test", "Delete Two"),
                    ("Batch Test", "Keep One"),
                    ("Other Test", "Foreign Product"),
                ],
            )
        self.manufacturer_id = manufacturer_id
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_id"] = 1
            session["admin_username"] = "admin"
            session["admin_role"] = "superadmin"
            session["csrf_token"] = "test-token"

    def tearDown(self):
        self.client = None
        gc.collect()
        application.DATABASE = self.original_database
        self.temporary_directory.cleanup()

    def test_batch_delete_only_removes_selected_manufacturer_products(self):
        with application.get_db() as database:
            rows = database.execute(
                "SELECT id, name FROM products WHERE name LIKE 'Delete %' OR name = 'Foreign Product'"
            ).fetchall()
            ids = {row["name"]: row["id"] for row in rows}

        response = self.client.post(
            f"/admin/manufacturers/{self.manufacturer_id}/products/batch-delete",
            data={
                "csrf_token": "test-token",
                "product_ids": [
                    str(ids["Delete One"]),
                    str(ids["Delete Two"]),
                    str(ids["Foreign Product"]),
                ],
            },
        )

        self.assertEqual(response.status_code, 302)
        response.close()
        with application.get_db() as database:
            remaining = {
                row[0] for row in database.execute(
                    "SELECT name FROM products WHERE name IN ('Delete One', 'Delete Two', 'Keep One', 'Foreign Product')"
                )
            }
        self.assertEqual(remaining, {"Keep One", "Foreign Product"})


if __name__ == "__main__":
    unittest.main()
