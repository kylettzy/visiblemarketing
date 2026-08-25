import json
import unittest
from unittest.mock import patch

import app as application


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "VTIC ready"}]}}
                ]
            }
        ).encode("utf-8")


class GeminiRestClientTests(unittest.TestCase):
    @patch("app.urllib.request.urlopen", return_value=FakeResponse())
    def test_rest_fallback_returns_generated_text(self, urlopen):
        client = application.GeminiRestClient("test-key")
        response = client.models.generate_content(
            model="gemini-test",
            contents="Hello",
            config={"system_instruction": "Be concise", "temperature": 0.2},
        )

        self.assertEqual(response.text, "VTIC ready")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertNotIn("test-key", request.full_url)


if __name__ == "__main__":
    unittest.main()
