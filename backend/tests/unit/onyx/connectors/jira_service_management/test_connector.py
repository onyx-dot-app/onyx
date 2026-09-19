from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector

def test_jsm_connector_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
    )
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT
