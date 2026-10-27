"""The YouTrack issues check passes only after it reads an issue's comments,
and says so in an advisory when the scope holds no issue to read."""

from unittest.mock import MagicMock, create_autospec

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckOutput,
)
from onyx.connectors.youtrack.capability_checks import build_youtrack_indexing_checks
from onyx.connectors.youtrack.models import YouTrackIssue, YouTrackProject
from onyx.connectors.youtrack.source_operations import YouTrackSourceOperations

_PROJECT = {"id": "0-1", "shortName": "ABC", "name": "Alpha"}


def _issues_check() -> CapabilityCheck:
    return next(
        check
        for check in build_youtrack_indexing_checks()
        if check.check_id == "youtrack_issues"
    )


def _run(ops: MagicMock, projects: list[str]) -> CheckOutput | None:
    return _issues_check().run(
        CapabilityCheckContext(
            source=DocumentSource.YOUTRACK,
            credential_json={},
            connector_specific_config={
                "base_url": "https://example.youtrack.cloud",
                "projects": projects,
            },
            source_operations=ops,
        )
    )


def _ops(issues: list[YouTrackIssue], archived: bool = False) -> MagicMock:
    ops = create_autospec(YouTrackSourceOperations, instance=True)
    ops.list_projects.return_value = [
        YouTrackProject.model_validate({**_PROJECT, "archived": archived})
    ]
    ops.iterate_slim_issues.return_value = iter([issues])
    ops.iterate_issues.return_value = iter([issues])
    return ops


def test_reading_an_issues_comments_passes_without_advisory() -> None:
    issue = YouTrackIssue.model_validate(
        {
            "id": "2-1",
            "idReadable": "ABC-1",
            "created": 1,
            "updated": 1,
            "project": _PROJECT,
        }
    )
    ops = _ops([issue])

    assert _run(ops, ["ABC"]) is None
    ops.list_issue_comments.assert_called_once_with(issue_id="2-1")


def test_no_issue_to_read_passes_with_an_advisory() -> None:
    for ops in (_ops([]), _ops([], archived=True)):
        output = _run(ops, ["ABC"])

        assert output is not None
        assert "comment access was not checked" in output.advisories[0].message
        ops.list_issue_comments.assert_not_called()
