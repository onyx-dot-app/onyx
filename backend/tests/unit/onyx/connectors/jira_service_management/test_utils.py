"""Unit tests for utility functions in JSM connector."""


from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestUtilityFunctions:
    """Test utility functions."""

    def test_quoted_jsm_project_quotes_key(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that quoted_jsm_project properly quotes the project key."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        quoted = connector.quoted_jsm_project
        assert quoted == f'"{jsm_project_key}"'
        assert quoted.startswith('"')
        assert quoted.endswith('"')

    def test_comment_email_blacklist_property(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test comment_email_blacklist property formatting."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
            comment_email_blacklist=["  test@example.com  ", "other@example.com"],
        )

        blacklist = connector.comment_email_blacklist
        assert isinstance(blacklist, tuple)
        assert "test@example.com" in blacklist
        assert "other@example.com" in blacklist
        # Should strip whitespace
        assert "  test@example.com  " not in blacklist
