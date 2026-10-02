"""Tests for the DocumentFailure.document_id round-trip invariant in the Jira connector.

`DocumentFailure.document_id` must equal the `Document.id` that the connector would have
produced for the same issue. Consumers rely on this to match a failure back to the document
it stands in for:

- `backend/onyx/background/celery/tasks/docprocessing/tasks.py` checks
  `document.id not in failed_document_ids`.
- `backend/onyx/background/indexing/run_targeted_reindex.py` computes
  `{d.id for d in documents} - failed_ids`.
- `backend/onyx/background/celery/celery_utils.py::_get_failure_id` reads the same field.

If the failure path used the bare issue key instead of the URL that `Document.id` uses, none
of these lookups would ever match, so a failed issue would look indexed forever.
"""

import time
from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.utils import build_jira_url
from onyx.connectors.models import ConnectorFailure, Document
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def create_mock_issue() -> Callable[..., MagicMock]:
    """Minimal mock Issue builder, mirroring the fixture in test_jira_checkpointing.py
    (not shared via conftest.py, so it is redefined here).
    """

    def _create_mock_issue(key: str) -> MagicMock:
        mock_issue = MagicMock(spec=Issue)
        mock_issue.fields = MagicMock()
        mock_issue.key = key
        mock_issue.fields.summary = "Test Issue"
        mock_issue.fields.updated = "2023-01-01T12:00:00.000+0000"
        mock_issue.fields.created = "2023-01-01T12:00:00.000+0000"
        mock_issue.fields.description = "Test Description"
        mock_issue.fields.labels = []

        mock_issue.fields.reporter = MagicMock()
        mock_issue.fields.reporter.displayName = "Test Creator"
        mock_issue.fields.reporter.emailAddress = "creator@example.com"

        mock_issue.fields.assignee = MagicMock()
        mock_issue.fields.assignee.displayName = "Test Assignee"
        mock_issue.fields.assignee.emailAddress = "assignee@example.com"

        mock_issue.fields.priority = MagicMock()
        mock_issue.fields.priority.name = "High"

        mock_issue.fields.status = MagicMock()
        mock_issue.fields.status.name = "In Progress"

        mock_issue.fields.resolution = MagicMock()
        mock_issue.fields.resolution.name = "Fixed"

        mock_issue.fields.project = MagicMock()
        mock_issue.fields.project.key = "TEST"
        mock_issue.fields.project.name = "Test Project"

        mock_issue.fields.issuetype = MagicMock()
        mock_issue.fields.issuetype.name = "Story"

        mock_issue.fields.parent = None

        mock_issue.raw = {"fields": {"description": "Test Description"}}

        return mock_issue

    return _create_mock_issue


def test_failure_document_id_matches_success_document_id(
    jira_connector: JiraConnector,
    jira_base_url: str,
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """Drive the connector twice for the same issue: once so it converts successfully,
    once with conversion patched to raise. The document_id captured from the failure path
    must equal the Document.id captured from the success path, and neither may be the bare
    issue key.
    """
    issue_key = "PROJ-123"

    jira_client = cast(JIRA, jira_connector._jira_client)
    jira_client._options = {"rest_api_version": "2"}
    search_issues_mock = cast(MagicMock, jira_client.search_issues)
    search_issues_mock.side_effect = [
        [create_mock_issue(key=issue_key)],
        [],
    ]

    success_outputs = load_everything_from_checkpoint_connector(
        jira_connector, 0, time.time()
    )
    success_items = [item for output in success_outputs for item in output.items]
    documents = [item for item in success_items if isinstance(item, Document)]
    assert len(documents) == 1
    success_document_id = documents[0].id

    search_issues_mock.side_effect = [
        [create_mock_issue(key=issue_key)],
        [],
    ]
    with pytest.MonkeyPatch.context() as monkeypatch:

        def _raise_on_conversion(
            *args: object,  # noqa: ARG001
            **kwargs: object,  # noqa: ARG001
        ) -> Document | None:
            raise ValueError("simulated conversion failure")

        monkeypatch.setattr(
            "onyx.connectors.jira.connector.process_jira_issue",
            _raise_on_conversion,
        )

        failure_outputs = load_everything_from_checkpoint_connector(
            jira_connector, 0, time.time()
        )

    failure_items = [item for output in failure_outputs for item in output.items]
    failures = [item for item in failure_items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    failed_document = failures[0].failed_document
    assert failed_document is not None
    failure_document_id = failed_document.document_id

    expected_document_id = build_jira_url(jira_base_url, issue_key)

    assert failure_document_id == expected_document_id
    assert success_document_id == expected_document_id
    assert failure_document_id == success_document_id

    # State the bug this test prevents: the bare issue key is not a valid document_id.
    assert failure_document_id != issue_key
    assert success_document_id != issue_key
