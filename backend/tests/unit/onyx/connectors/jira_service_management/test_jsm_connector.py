"""Unit tests for Jira Service Management connector."""
import sys
import unittest
from pathlib import Path

PATCH_BACKEND = Path(__file__).resolve().parents[5]
if str(PATCH_BACKEND) not in sys.path:
    sys.path.insert(0, str(PATCH_BACKEND))

from onyx.connectors.jira_service_management.client import JSMClient, JSMClientError, normalize_base_url
from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector


class TestJSMConnector(unittest.TestCase):
    def _mock_http(self, url: str, headers: dict, timeout: int):
        if "/servicedesk?" in url or url.endswith("/servicedesk"):
            return 200, {
                "isLastPage": True,
                "values": [{"id": "42", "projectKey": "ITSD", "projectName": "IT Service Desk"}],
            }
        if "/request?" in url:
            return 200, {
                "isLastPage": True,
                "values": [
                    {
                        "issueId": "1001",
                        "issueKey": "ITSD-101",
                        "serviceDeskId": "42",
                        "requestTypeId": "7",
                        "requestFieldValues": [
                            {"fieldId": "summary", "value": "VPN access broken"},
                            {"fieldId": "description", "value": "Cannot connect to corp VPN from macOS."},
                        ],
                        "currentStatus": {
                            "status": "Waiting for support",
                            "statusDate": {"iso8601": "2026-11-20T10:00:00Z"},
                        },
                        "reporter": {"displayName": "Alice Chen", "emailAddress": "alice@acme.com"},
                        "createdDate": {"iso8601": "2026-11-20T09:00:00Z"},
                        "_links": {"web": "https://acme.atlassian.net/browse/ITSD-101"},
                    }
                ],
            }
        if "/request/ITSD-101/comment" in url:
            return 200, {
                "isLastPage": True,
                "values": [
                    {
                        "id": "501",
                        "body": "Please reset your MFA token.",
                        "public": True,
                        "author": {"displayName": "Support Agent"},
                        "created": {"iso8601": "2026-11-20T10:30:00Z"},
                    },
                    {
                        "id": "502",
                        "body": "Internal escalation note",
                        "public": False,
                        "author": {"displayName": "Tier 2 Ops"},
                        "created": {"iso8601": "2026-11-20T10:45:00Z"},
                    },
                ],
            }
        return 404, {"errorMessage": "Not found"}

    def test_normalize_base_url_validation(self) -> None:
        self.assertEqual(normalize_base_url("https://acme.atlassian.net/"), "https://acme.atlassian.net")
        with self.assertRaises(ValueError):
            normalize_base_url("ftp://invalid")

    def test_resolve_project_and_load_public_comments_only(self) -> None:
        client = JSMClient(
            base_url="https://acme.atlassian.net",
            user_email="bot@acme.com",
            api_token="secret-token",
            http_get=self._mock_http,
        )
        conn = JiraServiceManagementConnector(
            jira_base_url="https://acme.atlassian.net",
            project_key="ITSD",
            include_internal_comments=False,
        )
        conn.set_client(client)
        conn.validate_connector_settings()

        batches = list(conn.load_from_state())
        self.assertEqual(len(batches), 1)
        doc = batches[0][0]
        self.assertEqual(doc["semantic_identifier"], "ITSD-101: VPN access broken")
        self.assertEqual(len(doc["sections"]), 2)
        self.assertIn("Please reset your MFA token.", doc["sections"][1]["text"])

    def test_include_internal_comments_and_time_window_filter(self) -> None:
        client = JSMClient(
            base_url="https://acme.atlassian.net",
            bearer_token="pat-123",
            http_get=self._mock_http,
        )
        conn = JiraServiceManagementConnector(
            jira_base_url="https://acme.atlassian.net",
            project_key="ITSD",
            include_internal_comments=True,
        )
        conn.set_client(client)
        batches = list(conn.load_from_state())
        self.assertEqual(len(batches[0][0]["sections"]), 3)

        # Poll window after ticket updated_at should return no batches
        future_batches = list(conn.poll_source(start=1_900_000_000.0, end=2_000_000_000.0))
        self.assertEqual(future_batches, [])

    def test_missing_project_raises_jsm_error(self) -> None:
        client = JSMClient(
            base_url="https://acme.atlassian.net",
            bearer_token="pat-123",
            http_get=self._mock_http,
        )
        with self.assertRaises(JSMClientError):
            client.resolve_service_desk_id("UNKNOWN")


if __name__ == "__main__":
    unittest.main()
