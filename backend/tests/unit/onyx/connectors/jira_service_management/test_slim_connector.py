"""Unit tests for slim connector functionality."""


from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestSlimConnector:
    """Test slim document retrieval."""

    def test_retrieve_all_slim_docs_method_exists(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that retrieve_all_slim_docs_perm_sync method exists."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        assert hasattr(connector, "retrieve_all_slim_docs_perm_sync")

    def test_connector_implements_slim_interface(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that connector implements SlimConnectorWithPermSync."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        # Verify it has the required method
        assert callable(getattr(connector, "retrieve_all_slim_docs_perm_sync", None))
