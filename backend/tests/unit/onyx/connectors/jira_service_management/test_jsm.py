import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.credential_families import (
    FAMILY_CREDENTIAL_CODECS,
    credential_family_for_source,
)
from onyx.connectors.factory import identify_connector_class
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira.source_operations import (
    JiraServiceManagementSourceOperations,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
    jira_planning_rule,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.planning_rule import ConnectorChangeOverride
from onyx.connectors.registry import CONNECTOR_CLASS_MAP
from onyx.connectors.source_operations import get_source_operations_class


def test_jsm_document_source_enum() -> None:
    assert hasattr(DocumentSource, "JIRA_SERVICE_MANAGEMENT")
    assert DocumentSource.JIRA_SERVICE_MANAGEMENT == "jira_service_management"


def test_jsm_registry_mapping() -> None:
    assert DocumentSource.JIRA_SERVICE_MANAGEMENT in CONNECTOR_CLASS_MAP
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.class_name == "JiraServiceManagementConnector"
    assert mapping.config_class == JiraServiceManagementConnectorConfig
    assert identify_connector_class(DocumentSource.JIRA_SERVICE_MANAGEMENT) is JiraServiceManagementConnector


def test_jsm_credential_family_codec() -> None:
    assert DocumentSource.JIRA_SERVICE_MANAGEMENT in FAMILY_CREDENTIAL_CODECS
    family = credential_family_for_source(DocumentSource.JIRA_SERVICE_MANAGEMENT)
    assert family is not None


def test_jsm_config_validation() -> None:
    # Valid config
    config = JiraServiceManagementConnectorConfig(
        jira_base_url="https://company.atlassian.net",
        project_key="HELP",
    )
    assert config.jira_base_url == "https://company.atlassian.net"
    assert config.project_key == "HELP"

    # Reject ORDER BY in JQL
    with pytest.raises(ValidationError):
        JiraServiceManagementConnectorConfig(
            jira_base_url="https://company.atlassian.net",
            jql_query="project = HELP ORDER BY created DESC",
        )

    # Valid JQL query
    config_jql = JiraServiceManagementConnectorConfig(
        jira_base_url="https://company.atlassian.net",
        jql_query="project = HELP AND status = 'Open'",
    )
    assert config_jql.jql_query == "project = HELP AND status = 'Open'"


def test_jsm_planning_rule() -> None:
    old_config = JiraServiceManagementConnectorConfig(
        jira_base_url="https://company.atlassian.net",
        project_key="HELP",
        jql_query="status = 'Open'",
    )
    new_config = JiraServiceManagementConnectorConfig(
        jira_base_url="https://company.atlassian.net",
        project_key="IT",
        jql_query="status = 'Closed'",
    )
    override = jira_planning_rule(old_config, new_config)
    assert isinstance(override, ConnectorChangeOverride)


def test_jsm_connector_initialization() -> None:
    # Standard initialization
    connector = JiraServiceManagementConnector(
        jira_base_url="https://company.atlassian.net",
        project_key="IT",
    )
    assert connector.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert connector.jira_project == "IT"
    assert connector.jira_base == "https://company.atlassian.net"


def test_jsm_load_credentials() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://company.atlassian.net",
        project_key="IT",
    )
    connector.load_credentials(
        {
            "jira_user_email": "agent@company.com",
            "jira_api_token": "token123",
        }
    )
    assert isinstance(connector.source_operations, JiraServiceManagementSourceOperations)


def test_jsm_gateway_and_capability_checks_registered() -> None:
    assert (
        get_source_operations_class(DocumentSource.JIRA_SERVICE_MANAGEMENT)
        is JiraServiceManagementSourceOperations
    )
    checks = get_capability_checks(DocumentSource.JIRA_SERVICE_MANAGEMENT)
    assert any(not check.is_fallback for check in checks)
    assert any(check.check_id == "jira_auth" for check in checks)


def test_jsm_document_extraction() -> None:
    issue = {
        "key": "IT-101",
        "fields": {
            "summary": "Cannot connect to VPN",
            "description": "User cannot connect to corporate VPN after password reset.",
            "labels": ["vpn", "network"],
            "reporter": {
                "displayName": "Alice Smith",
                "emailAddress": "alice@company.com",
            },
            "assignee": {
                "displayName": "Bob Tech",
                "emailAddress": "bob@company.com",
            },
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "resolution": None,
            "created": "2026-10-30T10:00:00.000+0000",
            "updated": "2026-10-31T12:00:00.000+0000",
            "issuetype": {"name": "Service Request"},
            "comment": {"comments": []},
            "project": {"key": "IT", "name": "IT Service Desk"},
        },
    }

    doc = process_jira_issue(
        jira_base_url="https://company.atlassian.net",
        issue=issue,
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
    )
    assert doc is not None
    assert doc.id == "https://company.atlassian.net/browse/IT-101"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.title == "IT-101 Cannot connect to VPN"
    assert doc.semantic_identifier == "IT-101: Cannot connect to VPN"
    assert "User cannot connect to corporate VPN" in doc.sections[0].text
    assert doc.metadata["key"] == "IT-101"
    assert doc.metadata["priority"] == "High"
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["project"] == "IT"
