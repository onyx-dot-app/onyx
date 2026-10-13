"""Tests that GitHub connector failures key on the same id as the successful Document.

DocumentFailure.document_id must equal the Document.id that the connector would have
produced for the same source item. Consumers rely on this equality to match failures
back to documents:

- backend/onyx/background/celery/tasks/docprocessing/tasks.py: `document.id not in
  failed_document_ids`
- backend/onyx/background/indexing/run_targeted_reindex.py: `{d.id for d in documents}
  - failed_ids`
- backend/onyx/background/celery/celery_utils.py: `_get_failure_id`

For GitHub, `Document.id` is the PR or issue `html_url`, not its number. If a
failure path used the number instead, these consumers would never recognize the
failure as belonging to the same item, and a failed document would look like it was
never attempted.
"""

import time
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import (
    GitHubCursorItem,
    GitHubPullRequest,
    GitHubRepository,
)
from onyx.connectors.github.source_operations import GitHubApiError
from onyx.connectors.models import ConnectorFailure
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


def test_pr_conversion_failure_document_id_matches_html_url(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """A PR conversion failure must key on the PR's html_url, not its number."""
    github_connector = build_github_connector()
    mock_source_operations.get_repository.return_value = create_repo()
    pr = create_pr(number=7, html_url="https://github.com/test-org/test-repo/pull/7")
    mock_source_operations.list_pull_requests.side_effect = [[pr], []]

    with patch(
        "onyx.connectors.github.connector._convert_pr_to_document",
        side_effect=RuntimeError("boom"),
    ):
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, time.time()
        )

    failures = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, ConnectorFailure)
    ]
    assert len(failures) == 1
    failed_document = failures[0].failed_document
    assert failed_document is not None
    assert failed_document.document_id == pr.html_url
    assert failed_document.document_id != str(pr.number)


def test_issue_conversion_failure_document_id_matches_html_url(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_issue: Callable[..., Any],
) -> None:
    """An issue conversion failure must key on the issue's html_url, not its number."""
    github_connector = build_github_connector()
    mock_source_operations.get_repository.return_value = create_repo()
    issue = create_issue(number=9)
    mock_source_operations.list_issues.side_effect = [[issue], []]

    with patch(
        "onyx.connectors.github.connector._convert_issue_to_document",
        side_effect=RuntimeError("boom"),
    ):
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, time.time()
        )

    failures = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, ConnectorFailure)
    ]
    assert len(failures) == 1
    failed_document = failures[0].failed_document
    assert failed_document is not None
    assert failed_document.document_id == issue.html_url
    assert failed_document.document_id != str(issue.number)


def test_detail_failure_of_a_cursor_item_is_a_document_failure(
    build_github_connector: Callable[..., GithubConnector],
    mock_source_operations: MagicMock,
    create_repo: Callable[..., GitHubRepository],
    create_pr: Callable[..., GitHubPullRequest],
) -> None:
    """A pull request read by cursor gets its details during conversion, so a
    failed read fails only that document."""
    github_connector = build_github_connector(include_issues=False)
    mock_source_operations.get_repository.return_value = create_repo()
    pr = create_pr(number=5)
    mock_source_operations.list_pull_requests.side_effect = GitHubApiError(
        "422", status_code=422, github_message="use cursor pagination"
    )
    mock_source_operations.iter_pull_requests_by_cursor.side_effect = [
        iter([GitHubCursorItem(item=pr, next_url="https://api.github.com/next")])
    ]
    mock_source_operations.get_pull_request.side_effect = GitHubApiError(
        "502", status_code=502
    )

    outputs = load_everything_from_checkpoint_connector(
        github_connector, 0, time.time()
    )

    failures = [
        item
        for output in outputs
        for item in output.items
        if isinstance(item, ConnectorFailure)
    ]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == pr.html_url
