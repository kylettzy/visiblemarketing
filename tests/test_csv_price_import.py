import gc
import io
import tempfile
import unittest
from pathlib import Path

import app as application


class CsvPriceImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = Path(self.temporary_directory.name) / "csv-import.db"
        application.initialize_database()
        with application.get_db() as database:
            self.manufacturer_id = database.execute(
                "INSERT INTO manufacturers (name) VALUES ('CSV Test')"
            ).lastrowid
            database.execute(
                """INSERT INTO products
                   (brand, name, category, price, description, source)
                   VALUES ('CSV Test', 'EAH-8', 'Access Control', NULL,
                           'Existing product', 'Partner quotation')"""
            )
        self.client = application.app.test_client()
        with self.client.session_transaction() as session:
            session["admin_id"] = 1
            session["admin_username"] = "admin"
            session["csrf_token"] = "test-token"

    def tearDown(self):
        self.client = None
        gc.collect()
        application.DATABASE = self.original_database
        self.temporary_directory.cleanup()

    def test_reimport_updates_existing_unpriced_product(self):
        csv_content = (
            "name,category,price,description,source\n"
            'EAH-8,Access Control,"?83,700.00",Existing product,Partner quotation\n'
        ).encode("cp1252")

        response = self.client.post(
            f"/admin/manufacturers/{self.manufacturer_id}/products/import",
            data={
                "csrf_token": "test-token",
                "csv_file": (io.BytesIO(csv_content), "products.csv"),
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 302)
        response.close()
        with application.get_db() as database:
            product = database.execute(
                "SELECT price FROM products WHERE brand = 'CSV Test' AND name = 'EAH-8'"
            ).fetchone()
        self.assertEqual(product["price"], 83700.0)


if __name__ == "__main__":
    unittest.main()
