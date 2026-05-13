from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraServiceManagementConnector
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


def test_jira_service_management_connector_uses_dedicated_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="HELP",
    )

    assert connector.source_type == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jira_connector_keeps_original_source() -> None:
    connector = JiraConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="ENG",
    )

    assert connector.source_type == DocumentSource.JIRA


def test_jira_service_management_registry_mapping() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]

    assert mapping.module_path == "onyx.connectors.jira.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"
