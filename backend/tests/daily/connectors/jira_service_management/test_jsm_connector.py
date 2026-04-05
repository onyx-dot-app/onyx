import os
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

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


_JSM_ISSUE_TYPE_FILTER = 'issuetype in ("Service Request", "Incident", "Problem", "Change", "Service Task")'


def _make_issue(issue_key: str, summary: str) -> Issue:
    issue = MagicMock(spec=Issue)
    issue.key = issue_key
    issue.raw = {"fields": {"description": f"Description for {issue_key}"}}
    issue.fields = SimpleNamespace(
        summary=summary,
        description=f"Description for {issue_key}",
        comment=SimpleNamespace(comments=[]),
        labels=[],
        updated="2026-01-02T03:04:05.000+0000",
        created="2026-01-01T00:00:00.000+0000",
        issuetype=SimpleNamespace(name="Service Request"),
        priority=SimpleNamespace(name="Medium"),
        status=SimpleNamespace(name="Open"),
        resolution=None,
        resolutiondate=None,
        duedate=None,
        reporter=SimpleNamespace(
            displayName="Reporter",
            emailAddress="reporter@example.com",
        ),
        assignee=SimpleNamespace(
            displayName="Assignee",
            emailAddress="assignee@example.com",
        ),
        parent=None,
        project=SimpleNamespace(key="HELP", name="Help Desk"),
    )
    return issue


def _make_jira_client(issue_pages: list[list[Issue]]) -> JIRA:
    jira_client = MagicMock(spec=JIRA)
    jira_client._options = {"rest_api_version": "2"}
    jira_client.search_issues.side_effect = issue_pages
    return jira_client


def _make_connector(jira_client: JIRA) -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url=os.environ.get("JIRA_BASE_URL", "https://example.atlassian.net"),
        project_key="HELP",
        comment_email_blacklist=[],
    )
    connector._jira_client = jira_client
    return connector


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


def _documents_from(
    yielded: list[Document | HierarchyNode | ConnectorFailure],
) -> list[Document]:
    return [item for item in yielded if isinstance(item, Document)]


def _format_jql_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def test_jsm_connector_source_and_jql() -> None:
    issue = _make_issue("HELP-1", "Service Request")
    jira_client = _make_jira_client([[issue]])
    connector = _make_connector(jira_client)

    start = 1_700_000_000.0
    end = 1_700_003_600.0

    yielded, checkpoint = _consume_generator(connector.load_from_checkpoint(start, end, connector.build_dummy_checkpoint()))
    documents = _documents_from(yielded)

    assert connector.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert len(documents) == 1
    assert documents[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert checkpoint.offset == 1
    assert checkpoint.has_more is False

    jira_client.search_issues.assert_called_once()
    search_kwargs = jira_client.search_issues.call_args.kwargs
    assert search_kwargs["startAt"] == 0
    assert search_kwargs["maxResults"] == 50
    assert 'project = "HELP"' in search_kwargs["jql_str"]
    assert _JSM_ISSUE_TYPE_FILTER in search_kwargs["jql_str"]
    assert f"updated >= '{_format_jql_time(start)}'" in search_kwargs["jql_str"]
    assert f"updated <= '{_format_jql_time(end)}'" in search_kwargs["jql_str"]


def test_jsm_connector_incremental_sync() -> None:
    jira_client = _make_jira_client(
        [
            [_make_issue("HELP-1", "First Request")],
            [_make_issue("HELP-2", "Second Request")],
            [],
        ]
    )
    connector = _make_connector(jira_client)
    checkpoint = connector.build_dummy_checkpoint()
    start = 1_700_000_000.0
    end = 1_700_003_600.0

    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 1):
        first_yielded, checkpoint = _consume_generator(connector.load_from_checkpoint(start, end, checkpoint))
        assert _documents_from(first_yielded)[0].source == (DocumentSource.JIRA_SERVICE_MANAGEMENT)
        assert checkpoint.offset == 1
        assert checkpoint.has_more is True

        second_yielded, checkpoint = _consume_generator(connector.load_from_checkpoint(start, end, checkpoint))
        assert _documents_from(second_yielded)[0].source == (DocumentSource.JIRA_SERVICE_MANAGEMENT)
        assert checkpoint.offset == 2
        assert checkpoint.has_more is True

        third_yielded, checkpoint = _consume_generator(connector.load_from_checkpoint(start, end, checkpoint))
        assert _documents_from(third_yielded) == []
        assert checkpoint.offset == 2
        assert checkpoint.has_more is False

    assert [call.kwargs["startAt"] for call in jira_client.search_issues.call_args_list] == [
        0,
        1,
        2,
    ]
