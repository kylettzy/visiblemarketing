import gc
import tempfile
import unittest
from pathlib import Path

import app as application


class ReviewChatTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = Path(self.temporary_directory.name) / "review-chat.db"
        application.initialize_database()
        with application.get_db() as database:
            database.execute(
                "INSERT INTO customers (full_name, email, password_hash) VALUES (?, ?, ?)",
                ("Customer One", "one@example.com", "unused"),
            )
            database.execute(
                "INSERT INTO customers (full_name, email, password_hash) VALUES (?, ?, ?)",
                ("Customer Two", "two@example.com", "unused"),
            )
            database.execute(
                """INSERT INTO review_requests
                   (customer_id, customer_name, customer_email, status)
                   VALUES (1, 'Customer One', 'one@example.com', 'submitted')"""
            )
        self.client = application.app.test_client()

    def tearDown(self):
        self.client = None
        application.DATABASE = self.original_database
        gc.collect()
        self.temporary_directory.cleanup()

    def customer_session(self, customer_id, name, email):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(
                customer_id=customer_id,
                customer_name=name,
                customer_email=email,
                csrf_token="test-token",
            )

    def test_customer_can_only_message_their_own_request(self):
        self.customer_session(1, "Customer One", "one@example.com")
        response = self.client.post(
            "/account/reviews/1/message",
            data={"csrf_token": "test-token", "message": "Can you confirm the lead time?"},
        )
        self.assertEqual(response.status_code, 302)
        with application.get_db() as database:
            message = database.execute(
                "SELECT sender_type, message FROM review_request_messages"
            ).fetchone()
        self.assertEqual(tuple(message), ("customer", "Can you confirm the lead time?"))

        self.customer_session(2, "Customer Two", "two@example.com")
        denied = self.client.post(
            "/account/reviews/1/message",
            data={"csrf_token": "test-token", "message": "Not my request"},
        )
        self.assertEqual(denied.status_code, 404)


if __name__ == "__main__":
    unittest.main()
