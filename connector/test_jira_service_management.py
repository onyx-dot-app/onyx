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
    def test_api_route_selection(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"total": 0, "issues": []}
        mock_get.return_value = resp

        # Server/DC with Bearer token must route to v2 search with startAt
        conn_dc = JiraServiceManagementConnector("https://jira.example.com", "my-token")
        conn_dc.get_tickets("HELP")
        mock_get.assert_called_with(
            "https://jira.example.com/rest/api/2/search",
            params={"jql": "project = 'HELP' ORDER BY created DESC, id DESC", "startAt": 0, "maxResults": 50, "fields": "*all"},
            headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Onyx-JSM-Connector/1.0", "Authorization": "Bearer my-token"},
            auth=None,
            timeout=(10.0, 30.0),
        )

        # Cloud with email must route to /rest/api/3/search/jql
        resp_cloud = MagicMock()
        resp_cloud.status_code = 200
        resp_cloud.json.return_value = {"issues": [], "isLast": True}
        mock_get.return_value = resp_cloud

        conn_cloud = JiraServiceManagementConnector("https://jira.example.com", "my-token", user_email="admin@example.com")
        conn_cloud.get_tickets("HELP")
        self.assertEqual(mock_get.call_args[0][0], "https://jira.example.com/rest/api/3/search/jql")

    @patch("requests.Session.get")
    def test_cloud_token_pagination(self, mock_get):
        # Cloud Page 1 returning nextPageToken
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = {
            "issues": [{"id": "1", "key": "JSM-1"}, {"id": "2", "key": "JSM-2"}],
            "nextPageToken": "token-page-2",
            "isLast": False,
        }

        # Cloud Page 2 with isLast=True
        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {
            "issues": [{"id": "3", "key": "JSM-3"}],
            "nextPageToken": None,
            "isLast": True,
        }

        mock_get.side_effect = [resp1, resp2]

        conn = JiraServiceManagementConnector("https://jira.example.com", "token", user_email="admin@example.com")
        tickets = conn.get_tickets("HELP", page_size=2)

        self.assertEqual(len(tickets), 3)
        self.assertEqual(mock_get.call_count, 2)

        # Assert token-based pagination was passed in call 2
        call1_params = mock_get.call_args_list[0].kwargs["params"]
        call2_params = mock_get.call_args_list[1].kwargs["params"]
        self.assertNotIn("nextPageToken", call1_params)
        self.assertEqual(call2_params["nextPageToken"], "token-page-2")

    @patch("requests.Session.get")
    def test_jql_combining_and_secondary_sort(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"issues": [], "isLast": True}
        mock_get.return_value = resp

        conn = JiraServiceManagementConnector("https://jira.example.com", "token", user_email="user@test.com")
        conn.get_tickets("HELP", jql="status = Open")
        call_params = mock_get.call_args[1]["params"]
        self.assertEqual(call_params["jql"], "(project = 'HELP') AND (status = Open) ORDER BY created DESC, id DESC")

    def test_zero_and_negative_limits(self):
        conn = JiraServiceManagementConnector("https://jira.example.com", "token")
        self.assertEqual(conn.get_tickets("HELP", max_tickets=0), [])

        with self.assertRaises(ValueError):
            conn.get_tickets("HELP", max_tickets=-5)

    @patch("requests.Session.get")
    def test_server_dc_pagination(self, mock_get):
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
    def test_pagination_without_total(self, mock_get):
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = {
            "issues": [{"id": "1", "key": "JSM-1"}, {"id": "2", "key": "JSM-2"}],
        }

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = {
            "issues": [{"id": "3", "key": "JSM-3"}],
        }

        resp3 = MagicMock()
        resp3.status_code = 200
        resp3.json.return_value = {
            "issues": [],
        }

        mock_get.side_effect = [resp1, resp2, resp3]

        conn = JiraServiceManagementConnector("https://jira.example.com", "token")
        tickets = conn.get_tickets("HELP", page_size=2)

        self.assertEqual(len(tickets), 3)
        self.assertEqual(mock_get.call_count, 3)
        offsets = [c.kwargs["params"]["startAt"] for c in mock_get.call_args_list]
        self.assertEqual(offsets, [0, 2, 3])

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
