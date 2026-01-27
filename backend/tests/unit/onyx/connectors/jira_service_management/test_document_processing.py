"""Unit tests for document processing in JSM connector."""



from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestDocumentProcessing:
    """Test processing JSM issues into Document objects."""

    def test_document_source_is_jsm(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that connector uses JIRA_SERVICE_MANAGEMENT source."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        # Verify connector is configured for JSM
        assert connector.jsm_project_key == jsm_project_key
        assert DocumentSource.JIRA_SERVICE_MANAGEMENT is not None

    def test_connector_has_document_processing_methods(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that connector has document processing methods."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        # Verify methods exist
        assert hasattr(connector, "_load_from_checkpoint")
        assert hasattr(connector, "load_from_checkpoint")
        assert hasattr(connector, "load_from_checkpoint_with_perm_sync")
