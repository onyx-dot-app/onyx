"""Unit tests for permission sync in JSM connector."""



from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestPermissionSync:
    """Test permission synchronization functionality."""

    def test_permission_cache_initialization(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that permission cache is initialized."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        assert connector._project_permissions_cache == {}

    def test_get_project_permissions_method_exists(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that _get_project_permissions method exists."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        assert hasattr(connector, "_get_project_permissions")

    def test_load_with_perm_sync_method_exists(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that load_from_checkpoint_with_perm_sync method exists."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        assert hasattr(connector, "load_from_checkpoint_with_perm_sync")
