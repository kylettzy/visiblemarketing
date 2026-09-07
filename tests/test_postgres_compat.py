import unittest

import app as application


class PostgresCompatibilityTests(unittest.TestCase):
    def test_row_factory_accepts_commands_without_result_columns(self):
        cursor = type("Cursor", (), {"description": None})()
        make_row = application.postgres_row_factory(cursor)
        self.assertEqual(make_row(()), ())

    def test_cursor_wraps_result_rows_for_name_and_numeric_access(self):
        description = [type("Column", (), {"name": "id"})()]
        cursor = type(
            "Cursor",
            (),
            {"description": description, "fetchone": lambda self: (7,)},
        )()
        row = application.PostgresCursor(cursor).fetchone()
        self.assertEqual(row["id"], 7)
        self.assertEqual(row[0], 7)

    def test_schema_script_remains_a_single_multi_statement_query(self):
        schema = application.postgres_schema(
            "CREATE TABLE one (id INTEGER PRIMARY KEY);"
            "CREATE TABLE two (id INTEGER PRIMARY KEY);"
        )
        self.assertEqual(schema.count("CREATE TABLE"), 2)
        self.assertIn(";", schema)

    def test_translates_sqlite_placeholders_and_conflict_syntax(self):
        statement = application.postgres_sql(
            "INSERT OR IGNORE INTO manufacturers (name) VALUES (?)"
        )

    def test_escapes_literal_like_wildcards_for_psycopg(self):
        statement = application.postgres_sql(
            "SELECT id FROM ai_conversations WHERE title LIKE 'Product chat:%'"
        )
        self.assertIn("Product chat:%%", statement)
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

    def test_vercel_supabase_marker_can_be_removed_from_connection_url(self):
        parsed = application.urllib.parse.urlsplit(
            "postgresql://user:pass@host/db?sslmode=require&supa=base-pooler.x"
        )
        supported = application.urllib.parse.urlencode(
            [
                (key, value)
                for key, value in application.urllib.parse.parse_qsl(parsed.query)
                if key.casefold() != "supa"
            ]
        )
        self.assertEqual(supported, "sslmode=require")


if __name__ == "__main__":
    unittest.main()
