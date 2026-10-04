"""Tests that GitHub connector failures key on the same id as the successful Document.

DocumentFailure.document_id must equal the Document.id that the connector would have
produced for the same source item. Consumers rely on this equality to match failures
back to documents:

- backend/onyx/background/celery/tasks/docprocessing/tasks.py: `document.id not in
  failed_document_ids`
- backend/onyx/background/indexing/run_targeted_reindex.py: `{d.id for d in documents}
  - failed_ids`
- backend/onyx/background/celery/celery_utils.py: `_get_failure_id`

For GitHub, `Document.id` is the PR or issue `html_url`, not its numeric `id`. If a
failure path used the numeric id instead, these consumers would never recognize the
failure as belonging to the same item, and a failed document would look like it was
never attempted.
"""

import time
from collections.abc import Callable
from unittest.mock import MagicMock, patch

from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import SerializedRepository
from onyx.connectors.models import ConnectorFailure
from tests.unit.onyx.connectors.github.test_github_checkpointing import (
    build_github_connector,
    create_mock_issue,
    create_mock_pr,
    create_mock_repo,
    mock_github_client,
    repo_owner,
    repositories,
)
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

__all__ = [
    "build_github_connector",
    "create_mock_issue",
    "create_mock_pr",
    "create_mock_repo",
    "mock_github_client",
    "repo_owner",
    "repositories",
]


def test_pr_conversion_failure_document_id_matches_html_url(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_pr: Callable[..., MagicMock],
) -> None:
    """A PR conversion failure must key on the PR's html_url, not its numeric id."""
    github_connector = build_github_connector()
    mock_repo = create_mock_repo()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    mock_pr = create_mock_pr(
        number=7, html_url="https://github.com/test-org/test-repo/pull/7"
    )
    mock_pr.id = 12345

    mock_repo.get_pulls.return_value = MagicMock()
    mock_repo.get_pulls.return_value.get_page.side_effect = [
        [mock_pr],
        [],
    ]

    with (
        patch.object(SerializedRepository, "to_Repository", return_value=mock_repo),
        patch(
            "onyx.connectors.github.connector._convert_pr_to_document",
            side_effect=RuntimeError("boom"),
        ),
    ):
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
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
    assert failed_document.document_id == mock_pr.html_url
    assert failed_document.document_id != str(mock_pr.id)


def test_issue_conversion_failure_document_id_matches_html_url(
    build_github_connector: Callable[..., GithubConnector],
    mock_github_client: MagicMock,
    create_mock_repo: Callable[..., MagicMock],
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """An issue conversion failure must key on the issue's html_url, not its numeric id."""
    github_connector = build_github_connector()
    mock_repo = create_mock_repo()
    github_connector.github_client = mock_github_client
    mock_github_client.get_repo.return_value = mock_repo

    mock_issue = create_mock_issue(number=9)
    mock_issue.id = 54321
    mock_issue.html_url = "https://github.com/test-org/test-repo/issues/9"

    mock_repo.get_pulls.return_value = MagicMock()
    mock_repo.get_pulls.return_value.get_page.return_value = []
    mock_repo.get_issues.return_value = MagicMock()
    mock_repo.get_issues.return_value.get_page.side_effect = [
        [mock_issue],
        [],
    ]

    with (
        patch.object(SerializedRepository, "to_Repository", return_value=mock_repo),
        patch(
            "onyx.connectors.github.connector._convert_issue_to_document",
            side_effect=RuntimeError("boom"),
        ),
    ):
        end_time = time.time()
        outputs = load_everything_from_checkpoint_connector(
            github_connector, 0, end_time
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
    assert failed_document.document_id == mock_issue.html_url
    assert failed_document.document_id != str(mock_issue.id)
