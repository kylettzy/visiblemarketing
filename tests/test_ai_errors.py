import unittest

import app as application


class ProviderError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or str(code))
        self.code = code


class AiErrorMessageTests(unittest.TestCase):
    def test_admin_receives_actionable_quota_message(self):
        with application.app.test_request_context("/"):
            application.session["admin_id"] = 1
            with self.assertRaisesRegex(RuntimeError, "quota or rate limit"):
                application.raise_friendly_gemini_error(ProviderError(429))

    def test_customer_does_not_receive_provider_billing_details(self):
        with application.app.test_request_context("/"):
            application.session["customer_id"] = 1
            with self.assertRaisesRegex(RuntimeError, "currently unavailable"):
                application.raise_friendly_gemini_error(ProviderError(429))

    def test_admin_receives_actionable_key_message(self):
        with application.app.test_request_context("/"):
            application.session["admin_id"] = 1
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                application.raise_friendly_gemini_error(ProviderError(403))


if __name__ == "__main__":
    unittest.main()
