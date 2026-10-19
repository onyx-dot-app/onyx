"""The Jira targeted reindex reads each failed issue again by the key that
ends its URL, through a bulk fetch on Cloud and one search per key on Server,
and keys every outcome on the issue's URL."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
)


def _failure(url: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=url, document_link=url),
        failure_message="synthetic",
    )


def test_server_reindex_searches_each_key_and_reports_the_rest(
    jira_connector: JiraConnector,
    jira_base_url: str,
    mock_source_operations: MagicMock,
    create_mock_issue: Callable[..., dict[str, Any]],
) -> None:
    found = build_jira_url(jira_base_url, "TEST-1")
    skipped = build_jira_url(jira_base_url, "TEST-2")
    missing = build_jira_url(jira_base_url, "TEST-3")
    foreign = "https://other.example.com/browse/TEST-4"
    mock_source_operations.search_issues.side_effect = [
        [create_mock_issue(key="TEST-1")],
        [create_mock_issue(key="TEST-2", labels=["secret"])],
        [],
    ]

    outputs = list(
        jira_connector.reindex(
            [_failure(found), _failure(skipped), _failure(missing), _failure(foreign)]
        )
    )

    documents = [o for o in outputs if isinstance(o, Document)]
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert [d.id for d in documents] == [found]
    assert any(isinstance(o, HierarchyNode) for o in outputs)
    assert sorted(
        f.failed_document.document_id for f in failures if f.failed_document
    ) == sorted([skipped, missing, foreign])
    assert [
        c.kwargs["jql"] for c in mock_source_operations.search_issues.call_args_list
    ] == ['key = "TEST-1"', 'key = "TEST-2"', 'key = "TEST-3"']
    mock_source_operations.bulk_fetch_issues.assert_not_called()


def test_cloud_reindex_bulk_fetches_the_keys(
    jira_connector: JiraConnector,
    jira_base_url: str,
    mock_source_operations: MagicMock,
    create_mock_issue: Callable[..., dict[str, Any]],
) -> None:
    mock_source_operations._is_cloud.return_value = True
    # TEST-9 moved: Jira answers under its new key, which no target named.
    mock_source_operations.bulk_fetch_issues.return_value = [
        create_mock_issue(key="TEST-1"),
        create_mock_issue(key="OTHER-9"),
    ]
    found = build_jira_url(jira_base_url, "TEST-1")
    missing = build_jira_url(jira_base_url, "TEST-9")

    outputs = list(jira_connector.reindex([_failure(found), _failure(missing)]))

    assert [o.id for o in outputs if isinstance(o, Document)] == [found]
    assert [
        o.failed_document.document_id
        for o in outputs
        if isinstance(o, ConnectorFailure) and o.failed_document
    ] == [missing]
    mock_source_operations.bulk_fetch_issues.assert_called_once_with(
        issue_ids=["TEST-1", "TEST-9"]
    )
    mock_source_operations.search_issues.assert_not_called()
