import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _parse_jsm_datetime,
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


def _mock_response(status_code: int, json_body: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    if status_code >= 400:
        import requests

        err = requests.exceptions.HTTPError(f"HTTP {status_code}")
        err.response = resp
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status = MagicMock()
    return resp


class TestJiraServiceManagementConnector(unittest.TestCase):
    def test_registry_mapping_and_config(self) -> None:
        self.assertIn(DocumentSource.JIRA_SERVICE_MANAGEMENT, CONNECTOR_CLASS_MAP)
        mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
        self.assertEqual(mapping.class_name, "JiraServiceManagementConnector")
        self.assertIs(mapping.config_class, JiraServiceManagementConnectorConfig)

        cfg = JiraServiceManagementConnectorConfig(
            project_key="ITSM",
            service_desk_ids="1,2",
            include_internal_comments=False,
        )
        self.assertEqual(cfg.project_key, "ITSM")
        self.assertFalse(cfg.include_internal_comments)

    def test_parse_jsm_datetime_formats(self) -> None:
        dt_epoch = _parse_jsm_datetime({"epochMillis": 1704067200000})
        self.assertEqual(dt_epoch, datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc))

        dt_iso = _parse_jsm_datetime({"iso8601": "2024-05-10T12:30:00+0000"})
        self.assertEqual(dt_iso, datetime(2024, 5, 10, 12, 30, tzinfo=timezone.utc))

    def test_missing_credentials_raises(self) -> None:
        connector = JiraServiceManagementConnector()
        with self.assertRaises(ConnectorMissingCredentialError):
            connector.load_credentials({})

    @patch("onyx.connectors.jira_service_management.connector.requests.get")
    def test_load_from_state_and_comment_filtering(self, mock_get: MagicMock) -> None:
        def side_effect(url: str, **kwargs: Any) -> MagicMock:
            if url.endswith("/rest/servicedeskapi/servicedesk"):
                return _mock_response(
                    200,
                    {
                        "values": [
                            {
                                "id": "10",
                                "projectKey": "ITSM",
                                "projectName": "IT Service Desk",
                            },
                            {
                                "id": "20",
                                "projectKey": "HRSD",
                                "projectName": "HR Service Desk",
                            },
                        ],
                        "isLastPage": True,
                    },
                )
            if url.endswith("/rest/servicedeskapi/request"):
                return _mock_response(
                    200,
                    {
                        "values": [
                            {
                                "issueId": "10001",
                                "issueKey": "ITSM-42",
                                "requestTypeId": "15",
                                "createdDate": {"epochMillis": 1704067200000},
                                "currentStatus": {
                                    "status": "Waiting for support",
                                    "statusCategory": "INDETERMINATE",
                                    "statusDate": {"epochMillis": 1704070800000},
                                },
                                "reporter": {
                                    "displayName": "Jane Reporter",
                                    "emailAddress": "jane@example.com",
                                },
                                "requestFieldValues": [
                                    {
                                        "fieldId": "summary",
                                        "label": "Summary",
                                        "value": "VPN gateway unreachable in EU-West",
                                    },
                                    {
                                        "fieldId": "description",
                                        "label": "Description",
                                        "value": "Users cannot establish WireGuard tunnel.",
                                    },
                                ],
                                "_links": {
                                    "web": "https://acme.atlassian.net/servicedesk/customer/portal/10/ITSM-42"
                                },
                            }
                        ],
                        "isLastPage": True,
                    },
                )
            if url.endswith("/rest/servicedeskapi/request/ITSM-42/comment"):
                return _mock_response(
                    200,
                    {
                        "values": [
                            {
                                "id": "c1",
                                "body": "We are investigating the VPN concentrator.",
                                "public": True,
                                "created": {"epochMillis": 1704074400000},
                                "author": {
                                    "displayName": "Alex Agent",
                                    "emailAddress": "alex@example.com",
                                },
                            },
                            {
                                "id": "c2",
                                "body": "Internal note: firewall rule #88 was rotated.",
                                "public": False,
                                "created": {"epochMillis": 1704078000000},
                                "author": {
                                    "displayName": "SecOps Bot",
                                    "emailAddress": "secops@example.com",
                                },
                            },
                        ],
                        "isLastPage": True,
                    },
                )
            if url.endswith("/rest/servicedeskapi/request/ITSM-42/sla"):
                return _mock_response(
                    200,
                    {
                        "values": [
                            {
                                "name": "Time to first response",
                                "ongoingCycle": {"breached": False},
                            }
                        ],
                        "isLastPage": True,
                    },
                )
            raise AssertionError(f"Unexpected URL: {url}")

        mock_get.side_effect = side_effect

        connector = JiraServiceManagementConnector(
            project_key="ITSM",
            include_internal_comments=False,
        )
        connector.load_credentials(
            {
                "jsm_base_url": "https://acme.atlassian.net/",
                "jsm_user_email": "bot@example.com",
                "jsm_api_token": "secret-token",
            }
        )

        batches = list(connector.load_from_state())
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 1)
        doc = batches[0][0]
        self.assertIsInstance(doc, Document)
        assert isinstance(doc, Document)
        self.assertEqual(doc.id, "JSM_REQUEST_ITSM-42")
        self.assertEqual(doc.source, DocumentSource.JIRA_SERVICE_MANAGEMENT)
        self.assertEqual(
            doc.semantic_identifier,
            "ITSM-42: VPN gateway unreachable in EU-West",
        )
        self.assertEqual(doc.metadata["project_key"], "ITSM")
        self.assertEqual(doc.metadata["status"], "Waiting for support")

        combined_text = "\n".join(s.text for s in doc.sections if s.text)
        self.assertIn("VPN gateway unreachable in EU-West", combined_text)
        self.assertIn("Time to first response: ongoing (breached=False)", combined_text)
        self.assertIn("We are investigating the VPN concentrator.", combined_text)
        self.assertNotIn("Internal note: firewall rule #88", combined_text)

    @patch("onyx.connectors.jira_service_management.connector.requests.get")
    def test_auth_error_mapping(self, mock_get: MagicMock) -> None:
        connector = JiraServiceManagementConnector()
        connector.load_credentials(
            {
                "jsm_base_url": "https://acme.atlassian.net",
                "jsm_bearer_token": "pat-token",
            }
        )

        mock_get.return_value = _mock_response(401, {"message": "Unauthorized"})
        with self.assertRaises(CredentialExpiredError):
            connector.validate_connector_settings()

        mock_get.return_value = _mock_response(403, {"message": "Forbidden"})
        with self.assertRaises(InsufficientPermissionsError):
            connector.validate_connector_settings()


if __name__ == "__main__":
    unittest.main()
