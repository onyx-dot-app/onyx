from collections.abc import Callable, Iterator
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks import findings_setting
from onyx.connectors.capability_checks.draft_runs import decide_draft_check_state
from onyx.connectors.capability_checks.findings import bounded_count, bounded_options
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckFinding,
    CheckFindingKey,
    CheckNotRunReason,
    CheckOutput,
    CountFinding,
    DraftCheckState,
    DraftCheckStateKind,
    OptionsFinding,
    aggregate_capability_verdict,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import (
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.db.enums import AccessType

_FOUND = CountFinding(key=CheckFindingKey.VISIBLE_SPACES, count=3)


class _Check(CapabilityCheck):
    def __init__(
        self,
        check_id: str,
        run: Callable[[], list[CheckFinding] | None],
        *,
        discovery: bool = False,
        required: bool = True,
        order: list[str] | None = None,
        access_types: frozenset[AccessType] | None = None,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=check_id,
            required=required,
            requires_connector_instance=False,
            discovery=discovery,
            access_types=access_types,
        )
        self._run = run
        self._order = order

    def run(
        self,
        context: CapabilityCheckContext,  # noqa: ARG002
    ) -> CheckOutput | None:
        if self._order is not None:
            self._order.append(self.check_id)
        findings = self._run()
        return CheckOutput(findings=findings) if findings is not None else None


def _context(access_type: AccessType | None = None) -> CapabilityCheckContext:
    return CapabilityCheckContext(
        source=DocumentSource.CONFLUENCE, credential_json={}, access_type=access_type
    )


def _found() -> list[CheckFinding]:
    return [_FOUND]


def _passes() -> None:
    return None


def _denied() -> None:
    raise InsufficientPermissionsError("denied")


def _broken() -> None:
    raise UnexpectedValidationError("broken")


def test_a_discovery_check_is_never_required() -> None:
    check: _Check = _Check("spaces", _found, discovery=True, required=True)

    assert check.required is False
    result: CapabilityCheckResult = run_capability_checks([check], _context())[0]
    assert result.discovery is True
    assert result.required is False


def test_discovery_runs_after_validation_whatever_the_registration_order() -> None:
    order: list[str] = []
    checks: list[CapabilityCheck] = [
        _Check("spaces", _found, discovery=True, order=order),
        _Check("token", _passes, order=order),
    ]

    results: list[CapabilityCheckResult] = run_capability_checks(checks, _context())

    assert order == ["token", "spaces"]
    assert [result.check_id for result in results] == ["token", "spaces"]
    assert results[1].findings == [_FOUND]


def test_discovery_does_not_run_after_a_required_failure() -> None:
    order: list[str] = []
    checks: list[CapabilityCheck] = [
        _Check("token", _denied, order=order),
        _Check("spaces", _found, discovery=True, order=order),
    ]

    results: list[CapabilityCheckResult] = run_capability_checks(checks, _context())

    assert order == ["token"]
    # Shown as "Not run" naming the failed check, not as a check that does
    # not apply.
    assert results[1].status == CapabilityCheckStatus.SKIPPED
    assert results[1].applicable is True
    assert results[1].not_run_reason == CheckNotRunReason.DEPENDENCY_FAILED
    assert results[1].blocked_by == "token"
    assert results[1].summary == "Not run: token failed"
    assert results[1].message == "Not run: token failed"


def test_a_discovery_check_that_does_not_apply_drops_out_after_a_failure() -> None:
    checks: list[CapabilityCheck] = [
        _Check("token", _denied),
        _Check(
            "spaces",
            _found,
            discovery=True,
            access_types=frozenset({AccessType.PUBLIC}),
        ),
    ]

    results: list[CapabilityCheckResult] = run_capability_checks(
        checks, _context(AccessType.PRIVATE)
    )

    assert results[1].status == CapabilityCheckStatus.SKIPPED
    assert results[1].applicable is False
    assert results[1].not_run_reason is None


def test_discovery_does_not_run_with_findings_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        findings_setting,
        "get_security_settings",
        lambda: MagicMock(allow_connector_check_findings=False),
    )
    order: list[str] = []

    results: list[CapabilityCheckResult] = run_capability_checks(
        [_Check("spaces", _found, discovery=True, order=order)], _context()
    )

    assert order == []
    assert results[0].status == CapabilityCheckStatus.SKIPPED


@pytest.mark.parametrize("discovery_run", [_denied, _broken])
def test_a_failed_discovery_check_does_not_change_the_verdict(
    discovery_run: Callable[[], None],
) -> None:
    results: list[CapabilityCheckResult] = run_capability_checks(
        [_Check("token", _passes), _Check("spaces", discovery_run, discovery=True)],
        _context(),
    )

    assert aggregate_capability_verdict(True, results) == CapabilityVerdict.PASSED


def test_only_discovery_results_aggregate_to_skipped() -> None:
    results: list[CapabilityCheckResult] = run_capability_checks(
        [_Check("spaces", _found, discovery=True)], _context()
    )

    # A capability is never PASSED on the basis of discovery alone.
    assert aggregate_capability_verdict(True, results) == CapabilityVerdict.SKIPPED


def test_the_draft_state_marks_a_discovery_check() -> None:
    state: DraftCheckState = decide_draft_check_state(
        _Check("spaces", _found, discovery=True), _context()
    )

    assert state.discovery is True
    assert state.required is False
    assert state.state == DraftCheckStateKind.PENDING


def _numbers(read: list[int]) -> Iterator[int]:
    for number in range(5000):
        read.append(number)
        yield number


def test_bounded_options_stop_at_the_cap() -> None:
    read: list[int] = []

    finding: OptionsFinding = bounded_options(
        _numbers(read),
        key=CheckFindingKey.VISIBLE_SPACES,
        field_name="space",
        value=str,
        label=lambda number: f"Space {number}",
    )

    assert len(finding.options) == MAX_FINDING_OPTIONS
    assert finding.truncated is True
    # Reads one past the cap to know there is more, and no further.
    assert len(read) == MAX_FINDING_OPTIONS + 1
    assert finding.options[0].label == "Space 0"


def test_bounded_options_under_the_cap_are_complete() -> None:
    finding: OptionsFinding = bounded_options(
        iter(["a", "b"]),
        key=CheckFindingKey.READABLE_CHANNELS,
        field_name="channels",
        value=str,
        label=str,
        detail=lambda name: f"#{name}",
    )

    assert [option.value for option in finding.options] == ["a", "b"]
    assert finding.options[1].detail == "#b"
    assert finding.truncated is False


def test_bounded_count_reports_a_lower_bound_at_the_cap() -> None:
    read: list[int] = []

    at_cap: CountFinding = bounded_count(
        _numbers(read), key=CheckFindingKey.VISIBLE_ORGANIZATION_USERS, cap=100
    )
    under_cap: CountFinding = bounded_count(
        iter(range(7)), key=CheckFindingKey.VISIBLE_ORGANIZATION_USERS, cap=100
    )

    assert (at_cap.count, at_cap.at_least) == (100, True)
    assert len(read) == 101
    assert (under_cap.count, under_cap.at_least) == (7, False)
