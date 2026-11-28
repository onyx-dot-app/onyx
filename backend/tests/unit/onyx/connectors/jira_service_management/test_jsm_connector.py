"""Unit tests for Jira Service Management connector."""
from datetime import datetime, timezone
import unittest

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import LoadConnector, PollConnector
from onyx.connectors.jira_service_management.client import (
    JSMClient,
    JSMClientError,
    normalize_base_url,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document, TextSection


class TestJSMConnector(unittest.TestCase):
    def _mock_http(self, url: str, headers: dict, timeout: int):
        if "/servicedesk?" in url or url.endswith("/servicedesk"):
            return 200, {
                "isLastPage": True,
                "values": [{"id": "42", "projectKey": "ITSD", "projectName": "IT Service Desk"}],
            }
        if "/rest/api/3/issue/ITSD-101" in url:
            return 200, {
                "id": "1001",
                "key": "ITSD-101",
                "fields": {"updated": "2026-11-20T10:35:00Z"},
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
        self.assertEqual(
            normalize_base_url("https://acme.atlassian.net/"),
            "https://acme.atlassian.net",
        )
        with self.assertRaises(ValueError):
            normalize_base_url("ftp://invalid")

    def test_connector_inherits_load_and_poll_interfaces(self) -> None:
        conn = JiraServiceManagementConnector(
            jira_base_url="https://acme.atlassian.net",
            project_key="ITSD",
        )
        self.assertIsInstance(conn, LoadConnector)
        self.assertIsInstance(conn, PollConnector)

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
        self.assertIsInstance(doc, Document)
        self.assertEqual(doc.source, DocumentSource.JIRA_SERVICE_MANAGEMENT)
        self.assertEqual(doc.semantic_identifier, "ITSD-101: VPN access broken")
        self.assertEqual(len(doc.sections), 2)
        self.assertIsInstance(doc.sections[1], TextSection)
        self.assertIn("Please reset your MFA token.", doc.sections[1].text)
        self.assertEqual(
            doc.doc_updated_at,
            datetime(2026, 11, 20, 10, 35, 0, tzinfo=timezone.utc),
        )

    def test_poll_captures_comment_or_edit_after_status_change(self) -> None:
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

        # Status changed at 10:00, but issue was edited at 10:35 and internal comment added at 10:45.
        # A 10:15 - 11:00 poll window must still include the ticket.
        start_ts = datetime(2026, 11, 20, 10, 15, 0, tzinfo=timezone.utc).timestamp()
        end_ts = datetime(2026, 11, 20, 11, 0, 0, tzinfo=timezone.utc).timestamp()
        batches = list(conn.poll_source(start=start_ts, end=end_ts))
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0][0].sections), 3)
        self.assertEqual(
            batches[0][0].doc_updated_at,
            datetime(2026, 11, 20, 10, 45, 0, tzinfo=timezone.utc),
        )

        # Window strictly after latest update returns no batches
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


    def test_mixed_timezone_offsets_compare_utc_instants(self) -> None:
        def tz_http(url: str, headers: dict, timeout: int):
            if "/rest/api/3/issue/ITSD-202" in url:
                # 01:30 -0500 == 06:30 UTC (later than 01:59 -0400 == 05:59 UTC)
                return 200, {"id": "2002", "key": "ITSD-202", "fields": {"updated": "2026-11-01T01:30:00-0500"}}
            if "/request?" in url:
                return 200, {
                    "isLastPage": True,
                    "values": [{
                        "issueId": "2002",
                        "issueKey": "ITSD-202",
                        "serviceDeskId": "42",
                        "requestTypeId": "7",
                        "requestFieldValues": [{"fieldId": "summary", "value": "DST offset check"}],
                        "currentStatus": {"status": "Open", "statusDate": {"iso8601": "2026-11-01T01:59:00-0400"}},
                        "createdDate": {"iso8601": "2026-11-01T00:00:00Z"},
                        "_links": {"web": "https://acme.atlassian.net/browse/ITSD-202"},
                    }],
                }
            if "/comment" in url:
                return 200, {"isLastPage": True, "values": []}
            return 404, {}

        client = JSMClient(base_url="https://acme.atlassian.net", bearer_token="pat", http_get=tz_http)
        conn = JiraServiceManagementConnector(jira_base_url="https://acme.atlassian.net", service_desk_id="42")
        conn.set_client(client)
        start_ts = datetime(2026, 11, 1, 6, 0, 0, tzinfo=timezone.utc).timestamp()
        end_ts = datetime(2026, 11, 1, 7, 0, 0, tzinfo=timezone.utc).timestamp()
        batches = list(conn.poll_source(start=start_ts, end=end_ts))
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][0].doc_updated_at, datetime(2026, 11, 1, 6, 30, 0, tzinfo=timezone.utc))

    def test_retryable_timestamp_lookup_failure_propagates(self) -> None:
        def rate_limited_http(url: str, headers: dict, timeout: int):
            if "/rest/api/3/issue/ITSD-101" in url:
                return 429, {"errorMessage": "Rate limit exceeded"}
            return self._mock_http(url, headers, timeout)

        client = JSMClient(base_url="https://acme.atlassian.net", bearer_token="pat", http_get=rate_limited_http)
        with self.assertRaises(JSMClientError) as ctx:
            list(client.iter_requests(service_desk_id="42", include_comments=False))
        self.assertEqual(ctx.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
