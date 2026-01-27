"""Unit tests for JQL query generation in JSM connector."""

from datetime import datetime
from datetime import timezone


from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestJQLQueryGeneration:
    """Test JQL query generation logic."""

    def test_jql_with_project_key_and_time_range(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client
    ):
        """Test JQL generation with project key and time range."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc).timestamp()

        jql = connector._get_jql_query(start, end)

        assert f'project = "{jsm_project_key}"' in jql
        assert "updated >= '2023-01-01 12:00'" in jql
        assert "updated <= '2023-01-02 12:00'" in jql
        assert "AND" in jql

    def test_jql_project_key_quoted(self, jira_base_url: str, mock_jira_client):
        """Test that project key is properly quoted in JQL."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key="TEST-PROJECT",
        )
        connector._jira_client = mock_jira_client

        start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc).timestamp()

        jql = connector._get_jql_query(start, end)

        assert 'project = "TEST-PROJECT"' in jql

    def test_jql_timezone_handling(self, jira_base_url: str, jsm_project_key: str, mock_jira_client):
        """Test that timezone is handled correctly in JQL."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        # Use UTC timestamps
        start = datetime(2023, 6, 15, 14, 30, 0, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 6, 16, 14, 30, 0, tzinfo=timezone.utc).timestamp()

        jql = connector._get_jql_query(start, end)

        # Should format as YYYY-MM-DD HH:MM
        assert "2023-06-15 14:30" in jql
        assert "2023-06-16 14:30" in jql

    def test_jql_structure(self, jira_base_url: str, jsm_project_key: str, mock_jira_client):
        """Test that JQL has correct structure."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        start = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        end = datetime(2023, 1, 2, 0, 0, 0, tzinfo=timezone.utc).timestamp()

        jql = connector._get_jql_query(start, end)

        # Should have project filter AND time range filters (start and end)
        parts = jql.split(" AND ")
        assert len(parts) == 3  # project, updated >=, updated <=
        assert parts[0].strip().startswith("project =")
        assert any("updated >=" in p for p in parts)
        assert any("updated <=" in p for p in parts)
