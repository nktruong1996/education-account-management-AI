import unittest
from unittest.mock import Mock, patch

import requests

from dynamic_fas.ui_client import (
    DynamicFasApiError,
    chat_with_dynamic_fas,
    reset_dynamic_fas_session,
)


class DynamicFasUiClientTests(unittest.TestCase):
    @patch("dynamic_fas.ui_client.requests.post")
    def test_chat_calls_dynamic_fas_chat_endpoint(self, post: Mock) -> None:
        response = Mock(ok=True)
        response.json.return_value = {"reply": "Thanks", "suggested_fields": {}}
        post.return_value = response
        payload = {
            "session_id": "fas-10-test",
            "fas_scheme_id": 10,
            "message": "Income decreased",
            "questions": [],
            "current_answers": {},
        }

        result = chat_with_dynamic_fas("http://127.0.0.1:8001/", payload)

        self.assertEqual(result["reply"], "Thanks")
        post.assert_called_once_with(
            "http://127.0.0.1:8001/dynamic-fas/chat",
            json=payload,
            timeout=60,
        )

    @patch("dynamic_fas.ui_client.requests.post")
    def test_reset_calls_dynamic_fas_reset_endpoint(self, post: Mock) -> None:
        response = Mock(ok=True)
        response.json.return_value = {"session_id": "fas-10-test", "reset": True}
        post.return_value = response

        result = reset_dynamic_fas_session(
            "http://127.0.0.1:8001",
            "fas-10-test",
        )

        self.assertEqual(result["session_id"], "fas-10-test")
        self.assertTrue(result["reset"])
        self.assertNotIn("message", result)
        post.assert_called_once_with(
            "http://127.0.0.1:8001/dynamic-fas/reset-session",
            json={"session_id": "fas-10-test"},
            timeout=60,
        )

    @patch("dynamic_fas.ui_client.requests.post")
    def test_api_detail_is_exposed_as_a_user_facing_error(self, post: Mock) -> None:
        response = Mock(ok=False, status_code=422)
        response.json.return_value = {"detail": "Invalid questions"}
        post.return_value = response

        with self.assertRaisesRegex(DynamicFasApiError, "Invalid questions"):
            chat_with_dynamic_fas("http://127.0.0.1:8001", {})

    @patch("dynamic_fas.ui_client.requests.post")
    def test_connection_error_is_wrapped(self, post: Mock) -> None:
        post.side_effect = requests.ConnectionError("offline")

        with self.assertRaisesRegex(DynamicFasApiError, "Could not connect"):
            reset_dynamic_fas_session(
                "http://127.0.0.1:8001",
                "fas-10-test",
            )


if __name__ == "__main__":
    unittest.main()
