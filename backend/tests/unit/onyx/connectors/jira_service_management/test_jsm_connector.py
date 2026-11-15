"""Unit tests for Jira Service Management (JSM) connector."""

from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    process_jsm_issue,
    _extract_jsm_request_type,
    _extract_jsm_organizations,
    _extract_jsm_participants,
    _check_jsm_sla_breached,
    _get_jsm_comment_strs,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


def test_jsm_registry_mapping() -> None:
    """Verify Jira Service Management connector is correctly registered in CONNECTOR_CLASS_MAP."""
    assert DocumentSource.JIRA_SERVICE_MANAGEMENT in CONNECTOR_CLASS_MAP
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"
    assert mapping.config_class == JiraServiceManagementConnectorConfig


def test_jsm_connector_config_initialization() -> None:
    """Verify configuration validation and defaults."""
    config = JiraServiceManagementConnectorConfig(
        jira_base_url="https://company.atlassian.net",
        project_key="HELP",
        customer_visible_only=True,
    )
    assert config.jira_base_url == "https://company.atlassian.net"
    assert config.project_key == "HELP"
    assert config.customer_visible_only is True


def test_jsm_issue_processing_metadata_extraction() -> None:
    """Verify extraction of JSM specific metadata fields into Document."""
    mock_issue = {
        "key": "HELP-101",
        "fields": {
            "summary": "VPN connection drops after 5 minutes",
            "description": "Customer unable to maintain persistent tunnel connection.",
            "status": {"name": "Waiting for customer"},
            "priority": {"name": "High"},
            "reporter": {
                "displayName": "Alice Customer",
                "emailAddress": "alice@external.org",
            },
            "project": {"key": "HELP", "name": "IT Service Desk"},
            "created": "2026-11-15T12:00:00.000+0000",
            "updated": "2026-11-15T13:00:00.000+0000",
            "customfield_10010": {
                "requestType": {"name": "VPN / Network Access Request"}
            },
            "customfield_10002": [
                {"name": "Acme Corp"}
            ],
            "customfield_10003": [
                {"displayName": "Bob Manager", "emailAddress": "bob@external.org"}
            ],
            "timeToResolve": {
                "ongoingCycle": {"breached": True}
            },
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Agent John", "emailAddress": "john@internal.com"},
                        "body": "Hi Alice, could you please provide your diagnostic log?",
                        "jsdPublic": True,
                    },
                    {
                        "author": {"displayName": "Agent John", "emailAddress": "john@internal.com"},
                        "body": "INTERNAL NOTE: Check RADIUS server timeout settings on gateway 2.",
                        "jsdPublic": False,
                    },
                ]
            },
        },
    }

    doc = process_jsm_issue(
        jira_base_url="https://company.atlassian.net",
        issue=mock_issue,
        customer_visible_only=True,
        service_desk_id="12",
    )

    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.id == "https://company.atlassian.net/browse/HELP-101"
    assert doc.semantic_identifier == "JSM HELP-101: VPN connection drops after 5 minutes"
    
    # Metadata assertions
    assert doc.metadata["key"] == "HELP-101"
    assert doc.metadata["portal_status"] == "Waiting for customer"
    assert doc.metadata["request_type"] == "VPN / Network Access Request"
    assert doc.metadata["organizations"] == ["Acme Corp"]
    assert doc.metadata["request_participants"] == ["bob@external.org"]
    assert doc.metadata["sla_breached"] == "true"
    assert doc.metadata["service_desk_id"] == "12"

    # Comment visibility filtering assertions: internal note must be excluded
    section_text = doc.sections[0].text
    assert "Hi Alice, could you please provide your diagnostic log?" in section_text
    assert "INTERNAL NOTE: Check RADIUS server timeout settings on gateway 2." not in section_text


def test_jsm_comment_filtering_internal_property() -> None:
    """Verify internal notes marked via Atlassian sd.public.comment properties are excluded."""
    mock_issue = {
        "key": "HELP-202",
        "fields": {
            "summary": "Password reset request",
            "description": "User requested temp token.",
            "project": {"key": "HELP", "name": "IT Service Desk"},
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Agent Smith"},
                        "body": "Customer-visible resolution instructions.",
                        "properties": [
                            {"key": "sd.public.comment", "value": {"internal": False}}
                        ],
                    },
                    {
                        "author": {"displayName": "Agent Smith"},
                        "body": "Internal security whisper: verified employee badge #492.",
                        "properties": [
                            {"key": "sd.public.comment", "value": {"internal": True}}
                        ],
                    },
                ]
            },
        },
    }

    comments = _get_jsm_comment_strs(mock_issue, customer_visible_only=True)
    assert len(comments) == 1
    assert "Customer-visible resolution instructions." in comments[0]
    assert not any("Internal security whisper" in c for c in comments)
