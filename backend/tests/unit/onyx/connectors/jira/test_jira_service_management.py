"""Service-desk project fixtures use the same Jira ingestion path as software projects."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import JiraApiError
from onyx.connectors.models import Document, SlimDocument
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

RawIssueFactory = Callable[..., dict[str, Any]]
_START = 1672531200.0
_END = 1672617600.0


def _rich_text(text: str, cloud: bool) -> str | dict[str, Any]:
    if not cloud:
        return text
    return {
        "version": 1,
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _service_desk_issues(
    create_mock_issue: RawIssueFactory, cloud: bool
) -> list[dict[str, Any]]:
    comments = [
        {
            "body": _rich_text("Customer reply", cloud),
            "author": {"emailAddress": "customer@example.com"},
            "jsdPublic": True,
            "properties": [{"key": "sd.public.comment", "value": {"internal": False}}],
        },
        {
            "body": _rich_text("Internal agent note", cloud),
            "author": {"emailAddress": "agent@example.com"},
            "jsdPublic": False,
            "properties": [{"key": "sd.public.comment", "value": {"internal": True}}],
        },
        {
            "body": _rich_text("Excluded author", cloud),
            "author": {"emailAddress": "blacklist@example.com"},
            "jsdPublic": True,
        },
    ]
    issues: list[dict[str, Any]] = []
    for number, issue_type in enumerate(["Service Request", "Incident", "Change"], 1):
        issue = create_mock_issue(
            key=f"TEST-{number}",
            summary=f"Support ticket {number}",
            description=_rich_text(f"Support description {number}", cloud),
            issuetype_name=issue_type,
            project_name="Service Desk",
            comments=comments,
        )
        issue["fields"]["project"]["projectTypeKey"] = "service_desk"
        issues.append(issue)
    return issues


def _set_search_results(
    gateway: MagicMock, issues: list[dict[str, Any]], cloud: bool
) -> None:
    gateway._is_cloud.return_value = cloud
    gateway.search_issue_ids.return_value = JiraIssueIdPage(
        issue_ids=[issue["id"] for issue in issues], next_page_token=None
    )
    by_id = {issue["id"]: issue for issue in issues}

    def fetch_issues(*, issue_ids: list[str], **_: Any) -> list[dict[str, Any]]:
        return [by_id[issue_id] for issue_id in issue_ids]

    def search_issues(
        *, start_at: int, max_results: int, **_: Any
    ) -> list[dict[str, Any]]:
        return issues[start_at : start_at + max_results]

    gateway.bulk_fetch_issues.side_effect = fetch_issues
    gateway.search_issues.side_effect = search_issues


@pytest.mark.parametrize("cloud", [True, False], ids=["cloud", "data-center"])
def test_service_desk_project_uses_checkpointed_jira_ingestion(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    create_mock_issue: RawIssueFactory,
    cloud: bool,
) -> None:
    issues = _service_desk_issues(create_mock_issue, cloud)
    _set_search_results(mock_source_operations, issues, cloud)

    outputs = load_everything_from_checkpoint_connector(jira_connector, _START, _END)
    documents = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, Document)
    ]

    assert len(outputs) == 2
    assert outputs[0].next_checkpoint.has_more
    assert not outputs[-1].next_checkpoint.has_more
    for output in outputs:
        checkpoint = output.next_checkpoint
        assert (
            jira_connector.validate_checkpoint_json(checkpoint.model_dump_json())
            == checkpoint
        )
    assert len(documents) == len(issues)
    assert {document.source for document in documents} == {DocumentSource.JIRA}
    assert {document.metadata["issuetype"] for document in documents} == {
        "Service Request",
        "Incident",
        "Change",
    }
    for document in documents:
        assert document.id.endswith(f"/browse/{document.metadata['key']}")
        assert document.metadata["project"] == "TEST"
        assert document.metadata["project_name"] == "Service Desk"
        assert document.metadata["status"] == "In Progress"
        content = "\n".join(section.materialize_text() for section in document.sections)
        assert "Support description" in content
        assert "Customer reply" in content
        # Jira returns agent-visible notes too; this path has no visibility filter.
        assert "Internal agent note" in content
        assert "Excluded author" not in content

    search = (
        mock_source_operations.search_issue_ids
        if cloud
        else mock_source_operations.search_issues
    )
    for call in search.call_args_list:
        assert call.kwargs["jql"] == (
            f'project = "TEST" AND updated >= {int(_START * 1000)} '
            f"AND updated <= {int(_END * 1000)}"
        )

    _set_search_results(mock_source_operations, issues, cloud)
    slim_documents = [
        item
        for batch in jira_connector.retrieve_all_slim_docs(_START, _END)
        for item in batch
        if isinstance(item, SlimDocument)
    ]
    assert {document.id for document in slim_documents} == {
        document.id for document in documents
    }


@pytest.mark.parametrize("cloud", [True, False], ids=["cloud", "data-center"])
@pytest.mark.parametrize(
    "status_code,exception",
    [(401, CredentialExpiredError), (403, InsufficientPermissionsError)],
)
def test_service_desk_listing_does_not_hide_permission_failures(
    jira_connector: JiraConnector,
    mock_source_operations: MagicMock,
    cloud: bool,
    status_code: int,
    exception: type[Exception],
) -> None:
    mock_source_operations._is_cloud.return_value = cloud
    search = (
        mock_source_operations.search_issue_ids
        if cloud
        else mock_source_operations.search_issues
    )
    search.side_effect = JiraApiError("Access denied", status_code=status_code)

    # An empty result would let pruning remove tickets after a credential failure.
    with pytest.raises(exception):
        list(jira_connector.retrieve_all_slim_docs(_START, _END))
