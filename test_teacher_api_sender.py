import unittest
from unittest.mock import Mock, patch

import teacher_api_sender as sender


class TeacherApiSenderTests(unittest.TestCase):
    def setUp(self):
        sender.API_KEY = "test-key"

    def test_send_teacher_reply_posts_to_ai_email_reply_endpoint(self):
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": {"id": "message-123"}}

        with patch("teacher_api_sender.requests.post", return_value=mock_response) as mock_post:
            result = sender.send_teacher_reply("chat-123", "teacher-123", "Hello")

        self.assertTrue(result["success"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["data"], {"response": {"id": "message-123"}})
        self.assertEqual(
            mock_post.call_args.args[0],
            "https://api.preprod.coralacademy.com/ai-email/reply"
        )
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Ca-Teacher-Id", headers)
        self.assertEqual(
            mock_post.call_args.kwargs["json"],
            {"teacher_id": "teacher-123", "chat_id": "chat-123", "text": "Hello"}
        )

    def test_send_teacher_reply_returns_clear_error_without_api_key(self):
        sender.API_KEY = None

        result = sender.send_teacher_reply("chat-123", "teacher-123", "Hello")

        self.assertFalse(result["success"])
        self.assertIsNone(result["status_code"])
        self.assertIn("TEACHER_PORTAL_API_KEY", result["data"])

    def test_send_teacher_reply_returns_request_exception_as_result(self):
        with patch(
            "teacher_api_sender.requests.post",
            side_effect=sender.requests.RequestException("network down")
        ):
            result = sender.send_teacher_reply("chat-123", "teacher-123", "Hello")

        self.assertFalse(result["success"])
        self.assertIsNone(result["status_code"])
        self.assertEqual(result["data"], "network down")

    def test_delete_teacher_message_uses_ai_email_endpoint_and_teacher_id(self):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"ok": True}

        with patch("teacher_api_sender.requests.delete", return_value=mock_response) as mock_delete:
            result = sender.delete_teacher_message("chat-123", "message-123", "teacher-123")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            mock_delete.call_args.args[0],
            "https://api.preprod.coralacademy.com/ai-email/chats/chat-123/messages/message-123?teacher_id=teacher-123"
        )
        headers = mock_delete.call_args.kwargs["headers"]
        self.assertEqual(headers["x-api-key"], "test-key")


if __name__ == "__main__":
    unittest.main()
