from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import MagicMock

from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnectorCheckpoint
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode


def _consume_generator(
    generator: Generator[
        Document | HierarchyNode | ConnectorFailure,
        None,
        JiraConnectorCheckpoint,
    ],
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], JiraConnectorCheckpoint]:
    yielded: list[Document | HierarchyNode | ConnectorFailure] = []
    try:
        while True:
            yielded.append(next(generator))
    except StopIteration as e:
        return yielded, e.value


def test_jsm_connector_emits_jsm_source() -> None:
    issue = MagicMock(spec=Issue)
    issue.key = "HELP-1"
    issue.raw = {"fields": {"description": "Customer cannot log in"}}
    issue.fields = SimpleNamespace(
        summary="Cannot log in",
        description="Customer cannot log in",
        comment=SimpleNamespace(comments=[]),
        labels=[],
        updated="2023-01-01T00:00:00.000+0000",
        created="2023-01-01T00:00:00.000+0000",
        issuetype=SimpleNamespace(name="Service Request"),
        priority=SimpleNamespace(name="Medium"),
        status=SimpleNamespace(name="Open"),
        resolution=None,
        resolutiondate=None,
        duedate=None,
        reporter=None,
        assignee=None,
        parent=None,
        project=SimpleNamespace(key="HELP", name="Help Desk"),
    )

    jira_client = MagicMock(spec=JIRA)
    jira_client._options = {"rest_api_version": "2"}
    jira_client.search_issues.return_value = [issue]

    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="HELP",
        comment_email_blacklist=[],
    )
    connector._jira_client = jira_client

    start = 0.0
    end = 100.0
    yielded, _checkpoint = _consume_generator(
        connector.load_from_checkpoint(start, end, connector.build_dummy_checkpoint())
    )

    documents = [item for item in yielded if isinstance(item, Document)]
    assert len(documents) == 1
    assert documents[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    jira_client.search_issues.assert_called_once()
    search_kwargs = jira_client.search_issues.call_args.kwargs
    assert 'project = "HELP"' in search_kwargs["jql_str"]

