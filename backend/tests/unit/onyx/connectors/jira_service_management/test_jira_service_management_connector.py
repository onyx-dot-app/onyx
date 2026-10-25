import json
import unittest
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock, patch

import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _format_sla_metrics,
    _parse_jsm_datetime,
    _render_request_field_values,
)
from onyx.connectors.models import (
    ConnectorMissingCredentialError,
    Document,
    SlimDocument,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


def _mock_response(
    status_code: int,
    json_body: dict[str, Any] | list[Any],
    url: str = "https://acme.atlassian.net",
) -> requests.Response:
    """Return a real requests.Response with the supplied status code and encoded JSON body."""
    resp = requests.Response()
    resp.status_code = status_code
    resp.url = url
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body).encode("utf-8")
    return resp


class TestJiraServiceManagementConnector(unittest.TestCase):
    def test_registry_mapping_and_config(self) -> None:
        self.assertIn(DocumentSource.JIRA_SERVICE_MANAGEMENT, CONNECTOR_CLASS_MAP)
        mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
        self.assertEqual(
            mapping.module_path,
            "onyx.connectors.jira_service_management.connector",
        )
        self.assertEqual(mapping.class_name, "JiraServiceManagementConnector")
        self.assertEqual(
            mapping.config_class,
            JiraServiceManagementConnectorConfig,
        )

        config = JiraServiceManagementConnectorConfig(
            service_desk_ids=["10", "20"],
            project_key="ITSM",
            include_internal_comments=False,
            batch_size=25,
        )
        self.assertEqual(config.service_desk_ids, ["10", "20"])
        self.assertEqual(config.project_key, "ITSM")
        self.assertFalse(config.include_internal_comments)
        self.assertEqual(config.batch_size, 25)

    def test_https_validation_and_credential_loading(self) -> None:
        connector = JiraServiceManagementConnector()

        # Reject unencrypted HTTP URL
        with self.assertRaises(ConnectorValidationError):
            connector.load_credentials(
                {
                    "jsm_base_url": "http://insecure-jira.example.com",
                    "jsm_user_email": "admin@example.com",
                    "jsm_api_token": "token123",
                }
            )

        # Allow HTTPS
        connector.load_credentials(
            {
                "jsm_base_url": "https://secure-jira.example.com/",
                "jsm_user_email": "admin@example.com",
                "jsm_api_token": "token123",
            }
        )
        self.assertEqual(connector.base_url, "https://secure-jira.example.com")
        self.assertEqual(connector.user_email, "admin@example.com")
        self.assertEqual(connector.api_token, "token123")

        # Allow localhost HTTP for local testing
        connector.load_credentials(
            {
                "jsm_base_url": "http://localhost:8080",
                "jsm_bearer_token": "pat_abc",
            }
        )
        self.assertEqual(connector.base_url, "http://localhost:8080")
        self.assertEqual(connector.bearer_token, "pat_abc")

    def test_missing_credentials_raises(self) -> None:
        connector = JiraServiceManagementConnector()
        with self.assertRaises(ConnectorMissingCredentialError):
            connector.load_credentials({})

        with self.assertRaises(ConnectorMissingCredentialError):
            connector.load_credentials({"jsm_base_url": "https://acme.atlassian.net"})

    def test_parse_jsm_datetime_formats(self) -> None:
        self.assertIsNone(_parse_jsm_datetime(None))
        self.assertIsNone(_parse_jsm_datetime(""))

        # dict with epochMillis
        dt1 = _parse_jsm_datetime({"epochMillis": 1704067200000})
        self.assertIsNotNone(dt1)
        assert dt1 is not None
        self.assertEqual(dt1.year, 2024)
        self.assertEqual(dt1.tzinfo, timezone.utc)

        # ISO string ending in Z
        dt2 = _parse_jsm_datetime("2024-01-01T12:00:00.000Z")
        self.assertIsNotNone(dt2)
        assert dt2 is not None
        self.assertEqual(dt2.hour, 12)
        self.assertEqual(dt2.tzinfo, timezone.utc)

        # ISO string with 4-digit offset (+0200)
        dt3 = _parse_jsm_datetime("2024-01-01T14:00:00.000+0200")
        self.assertIsNotNone(dt3)
        assert dt3 is not None
        self.assertEqual(dt3.utcoffset(), timezone.utc.utcoffset(None))

    def test_field_rendering_and_sla_formatting_helpers(self) -> None:
        field_values = [
            {"fieldId": "summary", "label": "Summary", "value": "Server outage"},
            {
                "fieldId": "description",
                "label": "Description",
                "renderedValue": {"html": "<p>Critical database down</p>"},
            },
            {
                "fieldId": "custom_component",
                "label": "Component",
                "value": {"name": "Postgres Cluster"},
            },
            {
                "fieldId": "impacted_teams",
                "label": "Impacted Teams",
                "value": [{"name": "Checkout"}, {"name": "Billing"}],
            },
        ]
        summary, field_lines = _render_request_field_values(field_values, "DEFAULT")
        self.assertEqual(summary, "Server outage")
        self.assertIn("Description: <p>Critical database down</p>", field_lines)
        self.assertIn("Component: Postgres Cluster", field_lines)
        self.assertIn("Impacted Teams: Checkout, Billing", field_lines)

        slas = [
            {
                "name": "Time to first response",
                "ongoingCycle": {"breached": False},
            },
            {
                "name": "Time to resolution",
                "completedCycles": [{"breached": True}],
            },
        ]
        sla_lines = _format_sla_metrics(slas)
        self.assertEqual(
            sla_lines,
            [
                "Time to first response: ongoing (breached=False)",
                "Time to resolution: completed (breached=True)",
            ],
        )

    @patch("onyx.connectors.jira_service_management.connector.requests.Session.get")
    def test_load_from_state_and_comment_filtering(self, mock_get: MagicMock) -> None:
        def side_effect(url: str, **kwargs: Any) -> requests.Response:
            self.assertFalse(kwargs.get("allow_redirects", True))
            if url.endswith("/rest/servicedeskapi/servicedesk"):
                return _mock_response(
                    200,
                    {
                        "values": [
                            {
                                "id": "10",
                                "projectKey": "ITSM",
                                "projectName": "IT Service Desk",
                            }
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
                                "issueKey": "ITSM-42",
                                "issueId": "10042",
                                "requestTypeId": "5",
                                "createdDate": {"epochMillis": 1704067200000},
                                "currentStatus": {
                                    "status": "Waiting for support",
                                    "statusCategory": "IN_PROGRESS",
                                    "statusDate": {"epochMillis": 1704070800000},
                                },
                                "reporter": {
                                    "displayName": "Jane Doe",
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
        self.assertEqual(doc.metadata["service_desk_id"], "10")
        self.assertEqual(doc.metadata["status"], "Waiting for support")
        self.assertEqual(doc.metadata["request_type_id"], "5")

        # Verify primary owner is reporter
        self.assertIsNotNone(doc.primary_owners)
        assert doc.primary_owners is not None
        self.assertEqual(doc.primary_owners[0].email, "jane@example.com")

        # Verify secondary owner is public comment author
        self.assertIsNotNone(doc.secondary_owners)
        assert doc.secondary_owners is not None
        self.assertEqual(doc.secondary_owners[0].email, "alex@example.com")

        combined_text = "\n".join(s.text for s in doc.sections if s.text)
        self.assertIn("VPN gateway unreachable in EU-West", combined_text)
        self.assertIn("Time to first response: ongoing (breached=False)", combined_text)
        self.assertIn("We are investigating the VPN concentrator.", combined_text)
        # Internal comment filtered out
        self.assertNotIn("Internal note: firewall rule #88", combined_text)

    @patch("onyx.connectors.jira_service_management.connector.requests.Session.get")
    def test_retrieve_all_slim_docs(self, mock_get: MagicMock) -> None:
        def side_effect(url: str, **_kwargs: Any) -> requests.Response:
            if url.endswith("/rest/servicedeskapi/servicedesk"):
                return _mock_response(
                    200,
                    {
                        "values": [{"id": "1", "projectKey": "SUP"}],
                        "isLastPage": True,
                    },
                )
            if url.endswith("/rest/servicedeskapi/request"):
                return _mock_response(
                    200,
                    {
                        "values": [
                            {
                                "issueKey": "SUP-100",
                                "createdDate": {"epochMillis": 1704067200000},
                            }
                        ],
                        "isLastPage": True,
                    },
                )
            raise AssertionError(f"Unexpected URL: {url}")

        mock_get.side_effect = side_effect

        connector = JiraServiceManagementConnector()
        connector.load_credentials(
            {
                "jsm_base_url": "https://acme.atlassian.net",
                "jsm_bearer_token": "pat-token",
            }
        )

        slim_batches = list(connector.retrieve_all_slim_docs())
        self.assertEqual(len(slim_batches), 1)
        self.assertEqual(len(slim_batches[0]), 1)
        slim = slim_batches[0][0]
        self.assertIsInstance(slim, SlimDocument)
        assert isinstance(slim, SlimDocument)
        self.assertEqual(slim.id, "JSM_REQUEST_SUP-100")

    @patch("onyx.connectors.jira_service_management.connector.requests.Session.get")
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
