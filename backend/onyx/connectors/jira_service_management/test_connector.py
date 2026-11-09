import unittest
from .connector import JiraServiceManagementConnector


class TestJiraServiceManagementConnector(unittest.TestCase):
    def test_pagination_adf_parsing_and_sla_extraction(self):
        pages = [
            {
                "total": 2,
                "issues": [
                    {
                        "key": "JSM-101",
                        "fields": {
                            "summary": "VPN access request for production cluster",
                            "description": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "Need WireGuard profile issued."}],
                                    }
                                ],
                            },
                            "comment": {
                                "comments": [
                                    {
                                        "author": {"displayName": "SecOps Agent"},
                                        "body": "Approved after MFA verification.",
                                    }
                                ]
                            },
                            "status": {"name": "Waiting for support"},
                            "issuetype": {"name": "IT Help"},
                            "reporter": {"displayName": "Alice"},
                            "updated": "2026-11-08T16:00:00.000+0000",
                            "customfield_10010": {"ongoingCycle": {"breached": True}},
                        },
                    }
                ],
            },
            {
                "total": 2,
                "issues": [
                    {
                        "key": "JSM-102",
                        "fields": {
                            "summary": "Reset staging database credentials",
                            "description": "Plain text description",
                            "comment": {"comments": []},
                            "status": {"name": "Resolved"},
                            "issuetype": {"name": "Service Request"},
                            "reporter": {"displayName": "Bob"},
                            "updated": "2026-11-08T17:00:00.000+0000",
                            "customfield_10010": {"ongoingCycle": {"breached": False}},
                        },
                    }
                ],
            },
        ]
        call_idx = {"i": 0}

        def fake_transport(url, headers):
            idx = call_idx["i"]
            call_idx["i"] += 1
            return 200, pages[idx]

        conn = JiraServiceManagementConnector(
            base_url="https://acme.atlassian.net",
            project_key="jsm",
            email="bot@acme.io",
            api_token="secret_token",
            batch_size=1,
            transport=fake_transport,
        )
        docs = conn.fetch_tickets(start_timestamp=1700000000)
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0].id, "jsm:JSM:JSM-101")
        self.assertIn("Need WireGuard profile issued.", docs[0].text)
        self.assertIn("[SecOps Agent]: Approved after MFA verification.", docs[0].text)
        self.assertTrue(docs[0].sla_breached)
        self.assertFalse(docs[1].sla_breached)


if __name__ == "__main__":
    unittest.main()
