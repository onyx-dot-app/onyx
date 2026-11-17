"""
Tests for Jira Service Management Connector
"""

import unittest
from unittest.mock import MagicMock, patch
from .jira_service_management import JiraServiceManagementConnector, JiraApiError


class TestJiraServiceManagementConnector(unittest.TestCase):
    def test_auth_headers_bearer(self):
        conn = JiraServiceManagementConnector("https://jira.example.com", "my-token")
        auth, headers = conn._get_auth_and_headers()
        self.assertIsNone(auth)
        self.assertEqual(headers["Authorization"], "Bearer my-token")

    def test_auth_headers_basic(self):
        conn = JiraServiceManagementConnector(
            "https://jira.example.com", "my-token", user_email="admin@example.com"
        )
        auth, headers = conn._get_auth_and_headers()
        self.assertIsNotNone(auth)
        self.assertEqual(auth.username, "admin@example.com")
        self.assertEqual(auth.password, "my-token")

    @patch("requests.Session.get")
    def test_pagination(self, mock_get):
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = {
            "total": 3,
            "issues": [{"id": "1", "key": "JSM-1"}, {"id": "2", "key": "JSM-2"}],
        }

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {
            "total": 3,
            "issues": [{"id": "3", "key": "JSM-3"}],
        }

        mock_get.side_effect = [resp1, resp2]

        conn = JiraServiceManagementConnector("https://jira.example.com", "token")
        tickets = conn.get_tickets("HELP", page_size=2)

        self.assertEqual(len(tickets), 3)
        self.assertEqual(tickets[0]["key"], "JSM-1")
        self.assertEqual(tickets[2]["key"], "JSM-3")
        self.assertEqual(mock_get.call_count, 2)

    @patch("requests.Session.get")
    def test_http_error(self, mock_get):
        resp = MagicMock()
        resp.status_code = 401
        resp.reason = "Unauthorized"
        resp.text = "Invalid credentials"
        mock_get.return_value = resp

        conn = JiraServiceManagementConnector("https://jira.example.com", "token")
        with self.assertRaises(JiraApiError) as ctx:
            conn.get_tickets("HELP")
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
