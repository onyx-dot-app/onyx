"""JiraConnector.reindex on Server / Data Center, where the v2 JQL search
rejects a query that names a missing issue key. The live Cloud behavior is
covered by tests/daily/connectors/jira/test_jira_resolver.py."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraApiError
from onyx.connectors.models import ConnectorFailure, Document, DocumentFailure


def _failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message="synthetic",
        )
        for doc_id in doc_ids
    ]


def test_batch_error_falls_back_to_one_key_at_a_time(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    jira_base_url: str,
    create_mock_issue: Callable[..., dict[str, Any]],
) -> None:
    issues: dict[str, dict[str, Any]] = {
        "TEST-1": create_mock_issue(key="TEST-1"),
        "TEST-3": create_mock_issue(key="TEST-3", labels=["secret"]),
    }

    def search_issues(
        *,
        jql: str,
        start_at: int,
        max_results: int,  # noqa: ARG001
        fields: str | None = None,  # noqa: ARG001
    ) -> list[dict[str, Any]]:
        assert jql.startswith('project = "TEST" AND key in (')
        if start_at > 0:
            return []
        if '"TEST-2"' in jql:
            raise JiraApiError(
                "missing key",
                status_code=400,
                text='{"errorMessages": ["An issue with key \'TEST-2\' does not exist"]}',
            )
        return [issue for key, issue in issues.items() if f'"{key}"' in jql]

    mock_source_operations.search_issues.side_effect = search_issues
    doc_ids = [f"{jira_base_url}/browse/{key}" for key in ("TEST-1", "TEST-2")]
    skipped_id = f"{jira_base_url}/browse/TEST-3"

    results = list(jira_connector.reindex(_failures([*doc_ids, skipped_id])))

    docs = [r for r in results if isinstance(r, Document)]
    failures = {
        r.failed_document.document_id: r.failure_message
        for r in results
        if isinstance(r, ConnectorFailure) and r.failed_document is not None
    }
    assert [d.id for d in docs] == [doc_ids[0]]
    assert set(failures) == {doc_ids[1], skipped_id}
    assert "Failed to fetch Jira issue TEST-2" in failures[doc_ids[1]]
    assert "skipped" in failures[skipped_id]


def test_credential_error_fails_the_run(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    jira_base_url: str,
) -> None:
    mock_source_operations.search_issues.side_effect = JiraApiError(
        "unauthorized", status_code=401, text=None
    )

    with pytest.raises(CredentialExpiredError):
        list(jira_connector.reindex(_failures([f"{jira_base_url}/browse/TEST-1"])))
