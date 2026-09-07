import unittest

import app as application


class PostgresCompatibilityTests(unittest.TestCase):
    def test_translates_sqlite_placeholders_and_conflict_syntax(self):
        statement = application.postgres_sql(
            "INSERT OR IGNORE INTO manufacturers (name) VALUES (?)"
        )
        self.assertEqual(
            statement,
            "INSERT INTO manufacturers (name) VALUES (%s) ON CONFLICT DO NOTHING",
        )

    def test_translates_schema_primary_keys_and_forward_constraints(self):
        schema = application.postgres_schema(
            """
            CREATE TABLE example (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER,
                FOREIGN KEY (parent_id) REFERENCES parent(id)
            );
            """
        )
        self.assertIn("id BIGSERIAL PRIMARY KEY", schema)
        self.assertNotIn("FOREIGN KEY", schema)

    def test_supabase_google_marks_provider_available(self):
        original = application.SUPABASE_GOOGLE_AUTH
        try:
            application.SUPABASE_GOOGLE_AUTH = True
            self.assertTrue(application.oauth_provider_status()["google"])
        finally:
            application.SUPABASE_GOOGLE_AUTH = original


if __name__ == "__main__":
    unittest.main()
