import unittest
from unittest.mock import Mock, patch

import teacher_portal_api_reader as reader


class TeacherPortalApiReaderTests(unittest.TestCase):
    def setUp(self):
        reader.API_KEY = "test-key"
        reader.TOKEN = None
        reader.CA_ID = "ca-id"
        reader.WEBSITE_URL = "https://api.preprod.coralacademy.com/ai_email"

    def test_get_teachers_uses_teacher_collection_endpoint(self):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"response": {"teachers": []}}

        with patch("teacher_portal_api_reader.requests.get", return_value=mock_response) as mock_get:
            reader.get_teachers()

        self.assertEqual(
            mock_get.call_args.args[0],
            "https://api.preprod.coralacademy.com/ai-email/teachers"
        )
        self.assertEqual(mock_get.call_args.kwargs["headers"]["x-api-key"], "test-key")

    def test_get_chats_uses_teacher_specific_query_param(self):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"response": {"chats": []}}

        with patch("teacher_portal_api_reader.requests.get", return_value=mock_response) as mock_get:
            reader.get_chats("teacher-123")

        self.assertEqual(
            mock_get.call_args.args[0],
            "https://api.preprod.coralacademy.com/ai-email/chats?teacher_id=teacher-123"
        )
        self.assertNotIn("Authorization", mock_get.call_args.kwargs["headers"])

    def test_get_messages_includes_teacher_id_and_page(self):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"response": {"messages": []}}

        with patch("teacher_portal_api_reader.requests.get", return_value=mock_response) as mock_get:
            reader.get_messages("chat-123", "teacher-123")

        self.assertEqual(
            mock_get.call_args.args[0],
            "https://api.preprod.coralacademy.com/ai-email/chats/chat-123/messages?teacher_id=teacher-123&page=0"
        )

    def test_get_headers_uses_api_key_only(self):
        headers = reader.get_headers("teacher-123")

        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertNotIn("Authorization", headers)
        self.assertNotIn("Ca-Teacher-Id", headers)

    def test_get_headers_raises_clear_error_when_api_key_missing(self):
        reader.API_KEY = None

        with self.assertRaisesRegex(ValueError, "TEACHER_PORTAL_API_KEY"):
            reader.get_headers("teacher-123")


if __name__ == "__main__":
    unittest.main()
