"""Two-step rows: a check (the step) that completes another check's row.

The parent probes one item, such as one space or one user. Its step lists or
counts every item. Both show on the parent's row, and the step's result fills
that row once the parent passed. ``two_step_row`` holds the rules, so every
surface (the form, the detail page, the run history) shows the row the same
way.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from onyx.connectors.capability_checks.models import (
    INCOMPLETE_STATUSES,
    CapabilityCheck,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckErrorKind,
    CheckNotRunReason,
    CheckStep,
)

# Why a step that did not run still leaves the parent's row Successful: the
# step was cut short, it did not find a problem.
_UNFINISHED_NOT_RUN_REASONS: frozenset[CheckNotRunReason] = frozenset(
    {
        CheckNotRunReason.RATE_LIMITED,
        CheckNotRunReason.SKIPPED_BY_USER,
        CheckNotRunReason.STOPPED_BY_USER,
    }
)


def validate_step_links(checks: Sequence[CapabilityCheck]) -> None:
    """Raises ``ValueError`` unless every two-step link among ``checks`` (the
    checks of one source) is sound: the parent is one of ``checks`` and is not
    a step itself, it has no other step, and the step shows on its row and
    runs after it."""
    check_by_id: dict[str, CapabilityCheck] = {}
    for check in checks:
        check_by_id.setdefault(check.check_id, check)
    step_by_parent_id: dict[str, str] = {}
    for check in checks:
        if check.step is None:
            continue
        parent_id: str = check.step.step_of
        parent: CapabilityCheck | None = check_by_id.get(parent_id)
        if parent is None or parent_id == check.check_id:
            raise ValueError(
                f"{check.check_id} is a step of {parent_id}, which is not another "
                "check of its source."
            )
        if parent.step is not None:
            raise ValueError(
                f"{check.check_id} is a step of {parent_id}, which is a step itself."
            )
        if check.row_id != parent.row_id:
            raise ValueError(
                f"{check.check_id} shows on row {check.row_id}, not on the row of "
                f"its parent {parent_id} ({parent.row_id})."
            )
        if parent_id not in check.depends_on:
            raise ValueError(
                f"{check.check_id} does not depend on its parent {parent_id}."
            )
        other_step_id: str = step_by_parent_id.setdefault(parent_id, check.check_id)
        if other_step_id != check.check_id:
            raise ValueError(
                f"{parent_id} has two steps: {other_step_id} and {check.check_id}."
            )


class TwoStepEntry(BaseModel):
    """What the row rules read of one check: a result, or a draft state."""

    check_id: str
    row_id: str
    step: CheckStep | None = None
    # None while the check is pending or running.
    status: CapabilityCheckStatus | None
    applicable: bool = True
    partial: bool = False
    error_kind: CheckErrorKind | None = None
    not_run_reason: CheckNotRunReason | None = None
    summary: str | None = None

    @classmethod
    def of_result(cls, result: CapabilityCheckResult) -> "TwoStepEntry":
        return cls(
            check_id=result.check_id,
            row_id=result.row_id or result.check_id,
            step=result.step,
            status=result.status,
            applicable=result.applicable,
            partial=result.partial,
            error_kind=result.error_kind,
            not_run_reason=result.not_run_reason,
            summary=result.summary,
        )


class TwoStepRow(BaseModel):
    """How a two-step row shows. The row takes the state, line, description,
    details and findings of ``shown_check_id``, with two exceptions:
    ``counting`` makes it In progress, and ``caveat`` adds a caveat to the
    parent's Successful row. ``summary`` is the row's line in every case."""

    row_id: str
    parent_check_id: str
    step_check_id: str
    shown_check_id: str
    # The step runs after the parent passed.
    counting: bool = False
    summary: str | None = None
    # The step did not finish.
    caveat: str | None = None


def two_step_row(parent: TwoStepEntry, step: TwoStepEntry) -> TwoStepRow:
    """The row of ``parent`` and its ``step``.

    The parent decides the row until it passed. Then the step fills it:
    "counting…" while it runs, its own result when it passed, FAILED, or
    could not decide, and the parent's line with a caveat when it did not
    finish (a timeout, a rate limit, an error it does not know, or a skip).
    A step that does not apply, or that a gate of the run kept from running,
    leaves the parent's row as it is.
    """
    if step.step is None:
        raise ValueError(f"{step.check_id} is not a step.")
    parent_row = TwoStepRow(
        row_id=parent.row_id,
        parent_check_id=parent.check_id,
        step_check_id=step.check_id,
        shown_check_id=parent.check_id,
        summary=parent.summary,
    )
    step_row = parent_row.model_copy(
        update={"shown_check_id": step.check_id, "summary": step.summary}
    )
    if not parent.applicable:
        return step_row if step.applicable else parent_row
    if parent.status != CapabilityCheckStatus.PASSED or not step.applicable:
        return parent_row
    if step.status is None:
        return parent_row.model_copy(
            update={"counting": True, "summary": step.step.running_summary}
        )
    unfinished_row = parent_row.model_copy(
        update={"caveat": step.step.unfinished_caveat}
    )
    if step.status in (CapabilityCheckStatus.PASSED, CapabilityCheckStatus.FAILED):
        return step_row
    if step.status in INCOMPLETE_STATUSES:
        decided: bool = step.partial or step.error_kind == CheckErrorKind.INCONCLUSIVE
        return step_row if decided else unfinished_row
    if (
        step.status == CapabilityCheckStatus.STOPPED
        or step.not_run_reason in _UNFINISHED_NOT_RUN_REASONS
    ):
        return unfinished_row
    return parent_row


def two_step_rows(entries: Sequence[TwoStepEntry]) -> list[TwoStepRow]:
    """The two-step rows among ``entries``, in the order of their steps. A
    step whose parent is not among ``entries`` gets no row."""
    entry_by_id: dict[str, TwoStepEntry] = {}
    for entry in entries:
        entry_by_id.setdefault(entry.check_id, entry)
    rows: list[TwoStepRow] = []
    seen_step_ids: set[str] = set()
    for entry in entries:
        if entry.step is None or entry.check_id in seen_step_ids:
            continue
        seen_step_ids.add(entry.check_id)
        parent: TwoStepEntry | None = entry_by_id.get(entry.step.step_of)
        if parent is not None:
            rows.append(two_step_row(parent, entry))
    return rows


def two_step_rows_of_results(
    results: Sequence[CapabilityCheckResult],
) -> list[TwoStepRow]:
    return two_step_rows([TwoStepEntry.of_result(result) for result in results])
