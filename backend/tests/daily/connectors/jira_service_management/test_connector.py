"""Unit tests for the Jira Service Management (JSM) connector."""

from __future__ import annotations

from typing import Any
import unittest
import urllib.parse

from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector


class TestJiraServiceManagementConnector(unittest.TestCase):
    """Test suite verifying JSM token pagination, JQL epoch-ms bounds, ADF parsing, and null safety."""

    def test_pagination_adf_and_sla_extraction(self) -> None:
        """Verify `/rest/api/3/search/jql` pagination with `nextPageToken`, URL parameters, and SLA fields."""
        recorded_urls: list[str] = []

        pages: list[dict[str, Any]] = [
            {
                "nextPageToken": "tok_page_2",
                "isLast": False,
                "issues": [
                    {
                        "key": "ITSM-101",
                        "fields": {
                            "summary": "VPN gateway unreachable from EU office",
                            "description": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "Users in Frankfurt cannot connect.",
                                            },
                                            {"type": "hardBreak"},
                                        ],
                                    }
                                ],
                            },
                            "status": {"name": "Waiting for Support"},
                            "priority": {"name": "High"},
                            "issuetype": {"name": "Incident"},
                            "reporter": {"displayName": "Alice Ops"},
                            "updated": "2026-11-08T12:00:00.000+0000",
                            "customfield_10010": {"ongoingCycle": {"breached": True}},
                            "comment": {
                                "total": 1,
                                "comments": [
                                    {
                                        "author": {"displayName": "NetEng"},
                                        "body": "BGP route flapping.",
                                    }
                                ],
                            },
                        },
                    }
                ],
            },
            {
                "isLast": True,
                "issues": [
                    {
                        "key": "ITSM-102",
                        "fields": {
                            "summary": "Provision new MacBook Pro M4",
                            "description": "Standard onboarding hardware request.",
                            "status": {"name": "Resolved"},
                            "priority": {"name": "Low"},
                            "issuetype": {"name": "Service Request"},
                            "reporter": None,
                            "updated": "2026-11-08T13:00:00.000+0000",
                            "comment": {
                                "total": 1,
                                "comments": [
                                    {
                                        "author": None,
                                        "body": "Approved by manager.",
                                    }
                                ],
                            },
                        },
                    }
                ],
            },
        ]
        calls = {"idx": 0}

        def fake_transport(
            url: str, headers: dict[str, str]
        ) -> tuple[int, dict[str, Any]]:
            """Return canned paginated Jira responses while recording request URLs."""
            recorded_urls.append(url)
            idx = calls["idx"]
            calls["idx"] += 1
            return 200, pages[idx] if idx < len(pages) else {"issues": [], "isLast": True}

        conn = JiraServiceManagementConnector(
            base_url="https://acme.atlassian.net",
            project_key="itsm",
            user_email="bot@acme.io",
            api_token="secret",
            batch_size=1,
            transport=fake_transport,
        )
        docs = conn.fetch_tickets(start_timestamp=1700000000)
        self.assertEqual(len(docs), 2)
        self.assertEqual(len(recorded_urls), 2)

        first_qs = urllib.parse.parse_qs(urllib.parse.urlparse(recorded_urls[0]).query)
        second_qs = urllib.parse.parse_qs(urllib.parse.urlparse(recorded_urls[1]).query)
        self.assertNotIn("nextPageToken", first_qs)
        self.assertEqual(second_qs.get("nextPageToken"), ["tok_page_2"])
        self.assertIn('project = "ITSM"', first_qs["jql"][0])
        self.assertIn("updated >= 1700000000000", first_qs["jql"][0])

        self.assertEqual(docs[0].id, "jsm:ITSM-101")
        self.assertIn("Users in Frankfurt cannot connect.", docs[0].text)
        self.assertNotIn("hardBreak", docs[0].text)
        self.assertIn("[NetEng]: BGP route flapping.", docs[0].text)
        self.assertEqual(docs[0].metadata["sla_breached"], "true")

        self.assertEqual(docs[1].id, "jsm:ITSM-102")
        self.assertEqual(docs[1].metadata["sla_breached"], "false")
        self.assertEqual(docs[1].metadata["reporter"], "Customer")
        self.assertIn("[user]: Approved by manager.", docs[1].text)

    def test_invalid_project_key_raises_value_error(self) -> None:
        """Reject malformed or JQL-injection project keys during initialization."""
        with self.assertRaises(ValueError):
            JiraServiceManagementConnector(
                base_url="https://acme.atlassian.net",
                project_key='ITSM" OR project = "SECRET',
            )

    def test_comment_fetch_error_raises_runtime_error(self) -> None:
        """Verify non-200 comment response raises RuntimeError instead of silent truncation."""
        def error_transport(url: str, _headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
            if "/comment" in url:
                return 500, {"errorMessages": ["Internal Server Error"]}
            return 200, {
                "issues": [
                    {
                        "key": "ITSM-500",
                        "fields": {
                            "summary": "Database latency spike",
                            "comment": {"total": 5, "comments": []},
                        },
                    }
                ],
                "isLast": True,
            }

        conn = JiraServiceManagementConnector(
            base_url="https://acme.atlassian.net",
            project_key="ITSM",
            transport=error_transport,
        )
        with self.assertRaises(RuntimeError) as ctx:
            conn.fetch_tickets()
        self.assertIn("JSM comment fetch failed for ITSM-500: HTTP 500", str(ctx.exception))

    def test_infinite_pagination_loop_detection(self) -> None:
        """Detect and reject repeated nextPageToken that would cause an infinite loop."""
        def looping_transport(_url: str, _headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
            return 200, {
                "issues": [{"key": "ITSM-999", "fields": {"summary": "Loop item"}}],
                "nextPageToken": "stuck_token",
                "isLast": False,
            }

        conn = JiraServiceManagementConnector(
            base_url="https://acme.atlassian.net",
            project_key="ITSM",
            transport=looping_transport,
        )
        batches = conn.iter_ticket_batches()
        # First batch succeeds
        first_batch = next(batches)
        self.assertEqual(len(first_batch), 1)
        # Second batch detects repeated token and raises RuntimeError
        with self.assertRaises(RuntimeError) as ctx:
            next(batches)
        self.assertIn("Infinite JSM pagination loop detected", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
