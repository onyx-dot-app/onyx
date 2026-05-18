from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


def test_jsm_default_query_scopes_to_service_desk_projects() -> None:
    connector = JiraServiceManagementConnector(jira_base_url="https://example.atlassian.net")
    q = connector._get_jql_query(1715500000, 1715503600)
    assert "projectType = service_desk" in q
    assert "updated >=" in q
    assert "updated <=" in q


def test_jsm_custom_query_is_honored() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        jql_query='project = "HELP" AND statusCategory != Done',
    )
    q = connector._get_jql_query(1715500000, 1715503600)
    assert '(project = "HELP" AND statusCategory != Done)' in q
    assert "updated >=" in q
