"""Two-step rows: the registry's link rules, the merged row rules, and each
connector's links."""

from typing import Any
from uuid import uuid4

import pytest

from ee.onyx.connectors.capability_checks import get_perm_sync_capability_checks
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckRunSnapshot,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRunStatus,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
    CheckOutput,
    CheckStep,
    CredentialCapability,
)
from onyx.connectors.capability_checks.registry import get_capability_checks
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.capability_checks.two_step import (
    TwoStepEntry,
    TwoStepRow,
    two_step_row,
    two_step_rows_of_results,
    validate_step_links,
)
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.registry import CONNECTOR_CLASS_MAP

_STEP = CheckStep(
    step_of="parent",
    running_summary="Spaces visible, counting…",
    unfinished_caveat="Could not count every space.",
)


class _Check(CapabilityCheck[Any]):
    def __init__(
        self,
        check_id: str,
        *,
        step: CheckStep | None = None,
        depends_on: tuple[str, ...] = (),
        row_id: str | None = None,
        error: Exception | None = None,
        summary: str | None = None,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name="List spaces",
            requires_connector_instance=False,
            discovery=step is not None,
            depends_on=depends_on,
            row_id=row_id,
            step=step,
        )
        self._error = error
        self._summary = summary

    def run(self, context: CapabilityCheckContext) -> CheckOutput:  # noqa: ARG002
        if self._error is not None:
            raise self._error
        return CheckOutput(summary=self._summary)


def _step(**kwargs: Any) -> _Check:
    return _Check("step", step=_STEP, depends_on=("parent",), **kwargs)


# Registry validation


def test_a_sound_link_validates_and_takes_the_parent_row() -> None:
    step: _Check = _step()

    validate_step_links([_Check("parent"), step])

    assert step.row_id == "parent"


@pytest.mark.parametrize(
    "checks",
    [
        pytest.param([_step()], id="parent_missing"),
        pytest.param(
            [
                _Check("grandparent"),
                _Check(
                    "parent",
                    step=_STEP.model_copy(update={"step_of": "grandparent"}),
                    depends_on=("grandparent",),
                ),
                _step(row_id="grandparent"),
            ],
            id="chain",
        ),
        pytest.param([_Check("parent"), _step(row_id="other")], id="other_row"),
        pytest.param(
            [_Check("parent"), _Check("step", step=_STEP)], id="no_dependency"
        ),
        pytest.param(
            [
                _Check("parent"),
                _step(),
                _Check("step_two", step=_STEP, depends_on=("parent",)),
            ],
            id="two_steps",
        ),
        pytest.param(
            [_Check("parent", step=_STEP, depends_on=("parent",))], id="own_parent"
        ),
    ],
)
def test_an_unsound_link_raises(checks: list[CapabilityCheck[Any]]) -> None:
    with pytest.raises(ValueError):
        validate_step_links(checks)


# Each connector's links

_LINKS: dict[DocumentSource, dict[str, str]] = {
    DocumentSource.CONFLUENCE: {
        "confluence_space_listing": "confluence_spaces_visible",
    },
    DocumentSource.JIRA: {"jira_group_listing_complete": "jira_group_listing"},
    DocumentSource.GOOGLE_DRIVE: {
        "google_drive_user_count": "google_drive_workspace_users",
        "google_drive_shared_drive_listing": "google_drive_shared_drives",
    },
    DocumentSource.SLACK: {
        "slack_readable_channel_listing": "slack_public_channel_listing",
    },
    DocumentSource.ONEDRIVE: {"onedrive_drive_count": "onedrive_users"},
    DocumentSource.OUTLOOK: {"outlook_mailbox_count": "outlook_mailbox_listing"},
}


@pytest.mark.parametrize("source", sorted(CONNECTOR_CLASS_MAP, key=str))
def test_each_source_links_the_design_steps(source: DocumentSource) -> None:
    # As an EE registry returns them: the perm-sync checks are not in an OSS
    # unit test's registry.
    checks: list[CapabilityCheck[Any]] = [
        *get_capability_checks(source),
        *get_perm_sync_capability_checks(source),
    ]
    validate_step_links(checks)

    links: dict[str, str] = {
        check.check_id: check.step.step_of for check in checks if check.step
    }
    assert links == _LINKS.get(source, {})
    for check in checks:
        if check.step is not None:
            assert check.step.running_summary.endswith("…"), check.check_id
            assert check.step.unfinished_caveat.startswith("Could not count every "), (
                check.check_id
            )


# Merged row rules


def _entry(
    check_id: str,
    status: CapabilityCheckStatus | None,
    *,
    summary: str | None = None,
    applicable: bool = True,
    partial: bool = False,
    error_kind: CheckErrorKind | None = None,
    not_run_reason: CheckNotRunReason | None = None,
) -> TwoStepEntry:
    return TwoStepEntry(
        check_id=check_id,
        row_id="parent",
        step=_STEP if check_id == "step" else None,
        status=status,
        applicable=applicable,
        partial=partial,
        error_kind=error_kind,
        not_run_reason=not_run_reason,
        summary=summary,
    )


_PASSED_PARENT = _entry(
    "parent", CapabilityCheckStatus.PASSED, summary="Spaces visible"
)


def _shows(row: TwoStepRow) -> tuple[str, bool, str | None, str | None]:
    return (row.shown_check_id, row.counting, row.summary, row.caveat)


@pytest.mark.parametrize(
    "parent_status",
    [
        None,
        CapabilityCheckStatus.FAILED,
        CapabilityCheckStatus.INCOMPLETE,
        CapabilityCheckStatus.SKIPPED,
        CapabilityCheckStatus.STOPPED,
    ],
)
def test_the_parent_decides_the_row_until_it_passed(
    parent_status: CapabilityCheckStatus | None,
) -> None:
    parent = _entry("parent", parent_status, summary="No spaces visible")
    step = _entry("step", None)

    assert _shows(two_step_row(parent, step)) == (
        "parent",
        False,
        "No spaces visible",
        None,
    )


def test_the_row_counts_while_the_step_runs() -> None:
    assert _shows(two_step_row(_PASSED_PARENT, _entry("step", None))) == (
        "parent",
        True,
        "Spaces visible, counting…",
        None,
    )


@pytest.mark.parametrize(
    "step",
    [
        _entry("step", CapabilityCheckStatus.PASSED, summary="12 spaces visible"),
        _entry("step", CapabilityCheckStatus.FAILED, summary="12 spaces visible"),
        _entry(
            "step",
            CapabilityCheckStatus.INCOMPLETE,
            summary="12 spaces visible",
            error_kind=CheckErrorKind.INCONCLUSIVE,
        ),
        _entry(
            "step",
            CapabilityCheckStatus.INCOMPLETE,
            summary="12 spaces visible",
            partial=True,
        ),
    ],
    ids=["passed", "failed", "inconclusive", "partial"],
)
def test_a_finished_step_fills_the_row(step: TwoStepEntry) -> None:
    assert _shows(two_step_row(_PASSED_PARENT, step)) == (
        "step",
        False,
        "12 spaces visible",
        None,
    )


@pytest.mark.parametrize(
    "step",
    [
        _entry(
            "step", CapabilityCheckStatus.INCOMPLETE, error_kind=CheckErrorKind.TIMEOUT
        ),
        _entry(
            "step",
            CapabilityCheckStatus.INDETERMINATE,
            error_kind=CheckErrorKind.UNEXPECTED,
        ),
        _entry(
            "step",
            CapabilityCheckStatus.SKIPPED,
            not_run_reason=CheckNotRunReason.RATE_LIMITED,
        ),
        _entry(
            "step",
            CapabilityCheckStatus.SKIPPED,
            not_run_reason=CheckNotRunReason.SKIPPED_BY_USER,
        ),
        _entry(
            "step",
            CapabilityCheckStatus.STOPPED,
            not_run_reason=CheckNotRunReason.STOPPED_BY_USER,
        ),
    ],
    ids=["timeout", "legacy_unexpected", "rate_limited", "skipped", "stopped"],
)
def test_an_unfinished_step_adds_a_caveat_to_the_parent(step: TwoStepEntry) -> None:
    assert _shows(two_step_row(_PASSED_PARENT, step)) == (
        "parent",
        False,
        "Spaces visible",
        "Could not count every space.",
    )


@pytest.mark.parametrize(
    "step",
    [
        _entry("step", CapabilityCheckStatus.SKIPPED, applicable=False),
        _entry(
            "step",
            CapabilityCheckStatus.SKIPPED,
            not_run_reason=CheckNotRunReason.NOTHING_IN_SCOPE,
        ),
    ],
    ids=["not_applicable", "nothing_in_scope"],
)
def test_a_step_that_was_not_due_leaves_the_parent_row(step: TwoStepEntry) -> None:
    assert _shows(two_step_row(_PASSED_PARENT, step)) == (
        "parent",
        False,
        "Spaces visible",
        None,
    )


def test_a_step_without_its_applicable_parent_shows_alone() -> None:
    parent = _entry("parent", CapabilityCheckStatus.SKIPPED, applicable=False)
    step = _entry("step", CapabilityCheckStatus.PASSED, summary="12 spaces visible")

    assert two_step_row(parent, step).shown_check_id == "step"


# The rows on the API's results


def test_a_run_whose_step_times_out_reports_the_parent_row_with_a_caveat() -> None:
    results = run_capability_checks(
        [
            _Check("parent", summary="Spaces visible"),
            _step(error=UnexpectedValidationError("The listing broke.")),
        ],
        CapabilityCheckContext(source=DocumentSource.CONFLUENCE, credential_json={}),
    )

    assert [result.step for result in results] == [None, _STEP]
    (row,) = two_step_rows_of_results(results)
    assert row.parent_check_id == "parent"
    assert row.step_check_id == "step"
    assert _shows(row) == (
        "parent",
        False,
        "Spaces visible",
        "Could not count every space.",
    )


def _state(
    check_id: str, state: DraftCheckStateKind, summary: str | None = None
) -> DraftCheckState:
    return DraftCheckState(
        check_id=check_id,
        row_id="parent",
        step=_STEP if check_id == "step" else None,
        display_name="List spaces",
        capability=CredentialCapability.INDEXING,
        required=check_id == "parent",
        state=state,
        summary=summary,
        discovery=check_id == "step",
    )


def test_a_draft_snapshot_shows_counting_while_the_step_runs() -> None:
    snapshot = DraftCheckRunSnapshot(
        run_id=uuid4(),
        draft_key="draft",
        source=DocumentSource.CONFLUENCE,
        credential_id=1,
        access_type=None,
        status=DraftRunStatus.RUNNING,
        form_errors={},
        unknown_fields=[],
        checks=[
            _state("parent", DraftCheckStateKind.PASSED, "Spaces visible"),
            _state("step", DraftCheckStateKind.RUNNING),
        ],
    )

    (row,) = snapshot.two_step_rows
    assert _shows(row) == ("parent", True, "Spaces visible, counting…", None)
    assert snapshot.model_dump(mode="json")["two_step_rows"][0]["counting"] is True
