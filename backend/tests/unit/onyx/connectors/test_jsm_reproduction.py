import pytest
from onyx.configs.constants import DocumentSource

def test_jsm_document_source_registered():
    """Verify that DocumentSource has JIRA_SERVICE_MANAGEMENT."""
    assert hasattr(DocumentSource, "JIRA_SERVICE_MANAGEMENT")
    assert DocumentSource.JIRA_SERVICE_MANAGEMENT == "jira_service_management"

def test_jsm_connector_resolves_and_instantiates():
    """Verify that JSM connector class is registered and instantiable."""
    from onyx.connectors.factory import identify_connector_class
    from onyx.connectors.registry import CONNECTOR_CLASS_MAP

    source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert source in CONNECTOR_CLASS_MAP
    connector_cls = identify_connector_class(source)
    assert connector_cls.__name__ == "JiraServiceManagementConnector"

    # Instantiate connector
    connector = connector_cls(
        jira_base_url="https://company.atlassian.net",
        project_key="IT",
    )
    assert connector.jira_project == "IT"
    assert connector.jira_base == "https://company.atlassian.net"
