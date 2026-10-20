"""Integration tests for the check graph endpoint: a source's checks as a DAG,
for the connector form to schedule from."""

import requests

from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_GRAPH_URL = f"{API_SERVER_URL}/manage/admin/connector-checks/graph"

_JIRA_INDEXING_CHECK_IDS = {
    "jira_auth",
    "jira_scoped_token_auth",
    "jira_projects_visible",
    "jira_configured_project",
    "jira_jql_query",
    "jira_issue_read",
}


def _graph(user: DATestUser, source: DocumentSource) -> requests.Response:
    return client.get(_GRAPH_URL, params={"source": source.value}, headers=user.headers)


def test_jira_graph_serves_its_checks_and_dependencies(
    admin_user: DATestUser,
) -> None:
    # Under test: the graph of a source whose checks come from its JSON.
    response = _graph(admin_user, DocumentSource.JIRA)

    # Postcondition: the indexing checks with their metadata, and edges from
    # each prerequisite to its dependent, in the order the dependent lists them.
    response.raise_for_status()
    graph = response.json()
    assert graph["source"] == DocumentSource.JIRA.value
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert _JIRA_INDEXING_CHECK_IDS <= nodes.keys()
    assert nodes["jira_scoped_token_auth"]["row_id"] == "jira_auth"
    assert nodes["jira_auth"]["validates_binding"] is True
    assert nodes["jira_auth"]["conditional"] is True
    assert nodes["jira_issue_read"]["conditional"] is False
    edges = [(edge["prerequisite"], edge["dependent"]) for edge in graph["edges"]]
    assert [
        prerequisite
        for prerequisite, dependent in edges
        if dependent == "jira_projects_visible"
    ] == ["jira_auth", "jira_scoped_token_auth"]
    # Every edge names a served node.
    assert all(
        prerequisite in nodes and dependent in nodes
        for prerequisite, dependent in edges
    )


def test_source_without_named_checks_serves_its_fallback_node(
    admin_user: DATestUser,
) -> None:
    # Under test: a source with no check graph file.
    response = _graph(admin_user, DocumentSource.BITBUCKET)

    # Postcondition: the one legacy fallback node, with no edges.
    response.raise_for_status()
    graph = response.json()
    indexing = [node for node in graph["nodes"] if node["capability"] == "indexing"]
    assert [node["id"] for node in indexing] == ["bitbucket_connector_settings"]
    assert indexing[0]["is_fallback"] is True
    assert graph["edges"] == []


def test_basic_user_cannot_read_the_graph(basic_user: DATestUser) -> None:
    # Under test: a user without the connector-management permission.
    response = _graph(basic_user, DocumentSource.JIRA)

    # Postcondition: refused.
    assert response.status_code == 403
