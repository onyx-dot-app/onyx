from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import JiraServiceManagementConnector
from onyx.connectors.models import Document


def test_jira_service_management_requires_project_key() -> None:
    try:
        JiraServiceManagementConnector(
            jira_base_url="https://example.atlassian.net", project_key=""
        )
    except ValueError as e:
        assert "requires a project_key" in str(e)
    else:
        raise AssertionError("Expected ValueError for missing project_key")


def test_jira_service_management_jql_is_scoped_to_project() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="IT Support",
        jql_query="status = Open",
    )

    assert connector._get_jql_query(0, 3600) == (
        "(status = Open) AND project = 'IT Support' AND "
        "updated >= '1970-01-01 00:00' AND updated <= '1970-01-01 01:00'"
    )


def test_jira_service_management_document_source_is_distinct() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="IT",
    )
    jira_doc = Document(
        id="https://example.atlassian.net/browse/IT-1",
        sections=[],
        source=DocumentSource.JIRA,
        semantic_identifier="IT-1: Help needed",
        title="IT-1 Help needed",
        metadata={},
    )

    checkpoint = JiraConnectorCheckpoint(has_more=False)

    def parent_output():
        yield jira_doc
        return checkpoint

    with patch(
        "onyx.connectors.jira.connector.JiraConnector._load_from_checkpoint",
        return_value=parent_output(),
    ):
        output = connector._load_from_checkpoint("project = IT", checkpoint, False)
        document = next(output)
        try:
            next(output)
        except StopIteration as e:
            returned_checkpoint = e.value
        else:
            raise AssertionError("Expected Jira Service Management output to finish")

    assert document == jira_doc
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert returned_checkpoint == checkpoint
