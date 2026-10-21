"""Check dependencies: run order, the checks a dependency stops, the stop
after a rate limit, and the same rule for checks that ran side by side."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks import draft_runs, runner
from onyx.connectors.capability_checks.creation import (
    _defer_dependents_of_unfinished,
    _unfinished_results,
)
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckState,
    DraftCheckStateKind,
    cache_draft_result,
    wait_for_dependencies,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckNotApplicableError,
    CheckNotRunReason,
    CheckOutput,
    CredentialCapability,
    CredentialCapabilityReport,
)
from onyx.connectors.capability_checks.runner import (
    merge_capability_results,
    run_capability_checks,
    run_order,
    stop_blocked_results,
)
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    RateLimitedValidationError,
    UnexpectedValidationError,
)
from onyx.db.enums import CapabilityCheckTrigger


class _Check(CapabilityCheck):
    def __init__(
        self,
        check_id: str,
        *,
        depends_on: tuple[str, ...] = (),
        error: Exception | None = None,
        discovery: bool = False,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=f"Run {check_id}",
            requires_connector_instance=False,
            discovery=discovery,
            depends_on=depends_on,
        )
        self._error = error
        self.calls = 0

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:  # noqa: ARG002
        self.calls += 1
        if self._error is not None:
            raise self._error
        return None


def _run(
    checks: list[CapabilityCheck],
    prior_results: list[CapabilityCheckResult] | None = None,
) -> dict[str, CapabilityCheckResult]:
    context = CapabilityCheckContext(source=DocumentSource.SLACK, credential_json={})
    results = run_capability_checks(checks, context, prior_results=prior_results or [])
    return {result.check_id: result for result in results}


def _result(
    check_id: str, status: CapabilityCheckStatus, applicable: bool = True
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id=check_id,
        display_name=f"Run {check_id}",
        required=True,
        status=status,
        applicable=applicable,
    )


def test_a_check_runs_after_the_checks_it_depends_on() -> None:
    order = run_order(
        [
            _Check("content", depends_on=("list",)),
            _Check("listing", discovery=True),
            _Check("list", depends_on=("sign_in",)),
            _Check("sign_in"),
        ]
    )

    assert [check.check_id for check in order] == [
        "sign_in",
        "list",
        "content",
        "listing",
    ]


def test_a_cycle_is_an_error() -> None:
    with pytest.raises(ValueError):
        run_order([_Check("a", depends_on=("b",)), _Check("b", depends_on=("a",))])


def test_a_failed_dependency_stops_its_chain_without_calling_it() -> None:
    content = _Check("content", depends_on=("list",))
    results = _run(
        [
            _Check("sign_in", error=CredentialExpiredError("Rejected.")),
            _Check("list", depends_on=("sign_in",)),
            content,
            _Check("other"),
        ]
    )

    assert content.calls == 0
    assert results["list"].status == CapabilityCheckStatus.SKIPPED
    assert results["list"].not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    assert results["list"].blocked_by == "sign_in"
    assert results["list"].message == "Not run: Run sign_in failed"
    # The chain names the check that failed.
    assert results["content"].not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    assert results["content"].blocked_by == "sign_in"
    assert results["content"].message == "Not run: Run sign_in failed"
    assert results["other"].status == CapabilityCheckStatus.PASSED


def test_an_incomplete_dependency_stops_its_dependents() -> None:
    results = _run(
        [
            _Check("sample", error=UnexpectedValidationError("Unknown.")),
            _Check("comments", depends_on=("sample",)),
        ]
    )

    assert results["comments"].not_run_reason == CheckNotRunReason.DEPENDENCY_INCOMPLETE


def test_a_dependency_that_does_not_apply_is_left_out() -> None:
    results = _run(
        [
            _Check("scoped_sign_in", error=CheckNotApplicableError("Other token.")),
            _Check("sign_in"),
            _Check("list", depends_on=("sign_in", "scoped_sign_in")),
        ]
    )

    assert results["list"].status == CapabilityCheckStatus.PASSED


def test_a_prior_failure_stops_a_dependent() -> None:
    results = _run(
        [_Check("list", depends_on=("sign_in",))],
        prior_results=[_result("sign_in", CapabilityCheckStatus.FAILED)],
    )

    assert results["list"].not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED


def test_a_rate_limit_stops_the_rest_of_the_run() -> None:
    later = _Check("later")
    results = _run(
        [_Check("first", error=RateLimitedValidationError("Slow down.")), later]
    )

    assert results["first"].status == CapabilityCheckStatus.INCOMPLETE
    assert later.calls == 0
    assert results["later"].status == CapabilityCheckStatus.SKIPPED
    assert results["later"].not_run_reason == CheckNotRunReason.RATE_LIMITED


def test_results_that_ran_side_by_side_report_their_dependency() -> None:
    checks: list[CapabilityCheck] = [
        _Check("sign_in"),
        _Check("list", depends_on=("sign_in",)),
        _Check("content", depends_on=("list",)),
    ]
    results = stop_blocked_results(
        checks,
        [
            _result("content", CapabilityCheckStatus.FAILED),
            _result("sign_in", CapabilityCheckStatus.FAILED),
            _result("list", CapabilityCheckStatus.FAILED),
        ],
    )

    assert [(result.check_id, result.status) for result in results] == [
        ("content", CapabilityCheckStatus.SKIPPED),
        ("sign_in", CapabilityCheckStatus.FAILED),
        ("list", CapabilityCheckStatus.SKIPPED),
    ]
    assert results[0].not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    assert results[0].blocked_by == "sign_in"
    assert results[2].not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED


def test_a_dependency_that_ends_later_stops_a_finished_dependent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks: list[CapabilityCheck] = [
        _Check("sign_in"),
        _Check("list", depends_on=("sign_in",)),
    ]
    monkeypatch.setattr(runner, "get_capability_checks", lambda _source: checks)
    # The background run finished only the dependency; the dependent finished
    # earlier, within the creation budget.
    report = CredentialCapabilityReport(
        credential_id=1,
        source=DocumentSource.SLACK,
        checked_at=datetime.now(timezone.utc),
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        verdicts={},
        check_results=[_result("sign_in", CapabilityCheckStatus.INCOMPLETE)],
    )

    merged = merge_capability_results(
        report, [_result("list", CapabilityCheckStatus.PASSED)]
    )

    results = {result.check_id: result for result in merged.check_results}
    assert results["sign_in"].status == CapabilityCheckStatus.INCOMPLETE
    assert results["list"].status == CapabilityCheckStatus.SKIPPED
    assert results["list"].not_run_reason == CheckNotRunReason.DEPENDENCY_INCOMPLETE
    assert results["list"].blocked_by == "sign_in"


def test_unfinished_checks_after_a_failed_dependency_report_its_cause() -> None:
    checks: list[CapabilityCheck] = [
        _Check("content", depends_on=("list",)),
        _Check("sign_in"),
        _Check("list", depends_on=("sign_in",)),
        _Check("other"),
    ]
    results = _unfinished_results(
        checks,
        frozenset({"content", "list", "other"}),
        [_result("sign_in", CapabilityCheckStatus.FAILED)],
        "Pairing refused",
    )

    assert [(result.check_id, result.status) for result in results] == [
        ("content", CapabilityCheckStatus.SKIPPED),
        ("list", CapabilityCheckStatus.SKIPPED),
        ("other", CapabilityCheckStatus.INCOMPLETE),
    ]
    for result in results[:2]:
        assert result.not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
        assert result.blocked_by == "sign_in"


def test_a_check_that_finished_before_its_dependency_waits_for_it() -> None:
    checks: list[CapabilityCheck] = [
        _Check("sign_in"),
        _Check("list", depends_on=("sign_in",)),
        _Check("content", depends_on=("list",)),
        _Check("other"),
    ]
    finished, unfinished = _defer_dependents_of_unfinished(
        checks,
        [
            _result("list", CapabilityCheckStatus.FAILED),
            _result("content", CapabilityCheckStatus.PASSED),
            _result("other", CapabilityCheckStatus.PASSED),
        ],
        frozenset({"sign_in"}),
    )

    # The early failure does not block the pairing.
    assert [result.check_id for result in finished] == ["other"]
    assert unfinished == {"sign_in", "list", "content"}
    stored = _unfinished_results(checks, unfinished, finished, "Pairing refused")
    assert [(result.check_id, result.status) for result in stored] == [
        ("sign_in", CapabilityCheckStatus.INCOMPLETE),
        ("list", CapabilityCheckStatus.SKIPPED),
        ("content", CapabilityCheckStatus.SKIPPED),
    ]
    for result in stored[1:]:
        assert result.not_run_reason == CheckNotRunReason.DEPENDENCY_INCOMPLETE
        assert result.blocked_by == "sign_in"


def test_a_check_a_dependency_stops_drops_its_cached_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache: MagicMock = MagicMock()
    monkeypatch.setattr(draft_runs, "get_cache_backend", lambda: cache)

    cache_draft_result("list_key", _result("list", CapabilityCheckStatus.PASSED))
    cache.set.assert_called_once()
    cache.delete.assert_not_called()

    stopped = _result("list", CapabilityCheckStatus.SKIPPED).model_copy(
        update={"not_run_reason": CheckNotRunReason.DEPENDENCY_FAILED}
    )
    cache_draft_result("list_key", stopped)

    cache.set.assert_called_once()
    cache.delete.assert_called_once_with("list_key")


def test_a_check_waits_while_its_dependency_waits() -> None:
    def state(check_id: str, kind: DraftCheckStateKind) -> DraftCheckState:
        return DraftCheckState(
            check_id=check_id,
            display_name=check_id,
            capability=CredentialCapability.INDEXING,
            required=True,
            state=kind,
            message=(
                "Needs connector settings: space."
                if kind == DraftCheckStateKind.WAITING
                else ""
            ),
            missing_fields=["space"] if kind == DraftCheckStateKind.WAITING else [],
        )

    planned: list[tuple[CapabilityCheck, DraftCheckState]] = [
        (_Check("sign_in"), state("sign_in", DraftCheckStateKind.PENDING)),
        (
            _Check("find_space", depends_on=("sign_in",)),
            state("find_space", DraftCheckStateKind.WAITING),
        ),
        (
            _Check("content", depends_on=("find_space",)),
            state("content", DraftCheckStateKind.PENDING),
        ),
        (
            _Check("comments", depends_on=("content",)),
            state("comments", DraftCheckStateKind.PENDING),
        ),
    ]

    wait_for_dependencies(planned)

    states = {check.check_id: check_state for check, check_state in planned}
    assert states["sign_in"].state == DraftCheckStateKind.PENDING
    for check_id in ("content", "comments"):
        assert states[check_id].state == DraftCheckStateKind.WAITING
        assert states[check_id].missing_fields == ["space"]


def test_a_dependency_skipped_for_its_own_reason_stops_its_dependent() -> None:
    """A dependency that waits for a setting stops its dependent; a discovery
    check that a required failure skipped does not apply, so it does not."""
    results = _run(
        [_Check("count", depends_on=("find_space", "listing"))],
        prior_results=[
            _result("listing", CapabilityCheckStatus.SKIPPED, applicable=False),
            _result("find_space", CapabilityCheckStatus.SKIPPED),
        ],
    )

    assert results["count"].not_run_reason == CheckNotRunReason.DEPENDENCY_SKIPPED
    assert results["count"].blocked_by == "find_space"


class _PartialCheck(_Check):
    def run(self, context: CapabilityCheckContext) -> CheckOutput:  # noqa: ARG002
        self.calls += 1
        return CheckOutput(
            summary="1 of 2 drives not found",
            description="DRIVE-2 is not visible.",
            partial=True,
        )


def test_a_partial_find_is_incomplete_and_its_dependents_run() -> None:
    sample = _Check("sample", depends_on=("find",))
    results = _run([_PartialCheck("find"), sample])

    assert results["find"].status == CapabilityCheckStatus.INCOMPLETE
    assert results["find"].partial
    assert results["find"].summary == "1 of 2 drives not found"
    assert sample.calls == 1
    assert results["sample"].status == CapabilityCheckStatus.PASSED
