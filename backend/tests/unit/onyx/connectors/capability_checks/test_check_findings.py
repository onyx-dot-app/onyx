from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks.draft_runs import (
    CachedDraftResult,
    DraftCheckState,
    DraftCheckStateKind,
    apply_cached_result,
    apply_check_result,
    cached_check_result,
)
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_OPTIONS,
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckFinding,
    CheckFindingKey,
    CountFinding,
    CredentialCapabilityReport,
    FindingOption,
    OptionsFinding,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.db.enums import CapabilityCheckTrigger

_SPACES = OptionsFinding(
    key=CheckFindingKey.VISIBLE_SPACES,
    field_name="spaces",
    options=[FindingOption(value="ENG", label="Engineering")],
)
_USERS = CountFinding(key=CheckFindingKey.IMPERSONATABLE_USERS, count=1200)


class _FindingsCheck(CapabilityCheck):
    def __init__(
        self,
        run: Callable[[CapabilityCheckContext], list[CheckFinding] | None],
        check_id: str = "findings_check",
        capability: CredentialCapability = CredentialCapability.INDEXING,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name="Findings check",
            requires_connector_instance=False,
        )
        self._run = run

    def run(self, context: CapabilityCheckContext) -> list[CheckFinding] | None:
        return self._run(context)


def _context() -> CapabilityCheckContext:
    return CapabilityCheckContext(source=DocumentSource.CONFLUENCE, credential_json={})


def _raise_denied(_context: CapabilityCheckContext) -> list[CheckFinding] | None:
    raise InsufficientPermissionsError("denied")


def _result(findings: list[CheckFinding]) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id="findings_check",
        display_name="Findings check",
        required=True,
        status=CapabilityCheckStatus.PASSED,
        findings=findings,
    )


def test_a_passing_check_returns_its_findings() -> None:
    results: list[CapabilityCheckResult] = run_capability_checks(
        [_FindingsCheck(lambda _context: [_SPACES, _USERS])], _context()
    )

    assert results[0].status == CapabilityCheckStatus.PASSED
    assert results[0].findings == [_SPACES, _USERS]


def test_a_check_returning_none_has_no_findings() -> None:
    results: list[CapabilityCheckResult] = run_capability_checks(
        [_FindingsCheck(lambda _context: None)], _context()
    )

    assert results[0].findings == []


def test_a_failing_check_has_no_findings() -> None:
    results: list[CapabilityCheckResult] = run_capability_checks(
        [_FindingsCheck(_raise_denied)], _context()
    )

    assert results[0].status == CapabilityCheckStatus.FAILED
    assert results[0].findings == []


def test_a_mirrored_check_shares_its_findings() -> None:
    calls: list[int] = []

    def run(_context: CapabilityCheckContext) -> list[CheckFinding]:
        calls.append(1)
        return [_USERS]

    checks: list[CapabilityCheck] = [
        _FindingsCheck(run, capability=CredentialCapability.DOC_PERMISSION_SYNC),
        _FindingsCheck(run, capability=CredentialCapability.EXTERNAL_GROUP_SYNC),
    ]
    results: list[CapabilityCheckResult] = run_capability_checks(checks, _context())

    assert len(calls) == 1
    assert [result.findings for result in results] == [[_USERS], [_USERS]]


def test_findings_round_trip_through_the_stored_report() -> None:
    report: CredentialCapabilityReport = CredentialCapabilityReport(
        credential_id=1,
        source=DocumentSource.CONFLUENCE,
        checked_at=datetime.now(timezone.utc),
        trigger=CapabilityCheckTrigger.MANUAL,
        verdicts={},
        check_results=[_result([_SPACES, _USERS])],
    )

    stored: CredentialCapabilityReport = CredentialCapabilityReport.model_validate_json(
        report.model_dump_json()
    )

    assert stored.check_results[0].findings == [_SPACES, _USERS]


def test_a_result_stored_before_findings_still_parses() -> None:
    raw: dict[str, Any] = _result([]).model_dump(mode="json")
    del raw["findings"]

    assert CapabilityCheckResult.model_validate(raw).findings == []


def test_a_finding_this_version_does_not_know_is_dropped() -> None:
    raw: dict[str, Any] = _result([_USERS]).model_dump(mode="json")
    raw["findings"] += [
        {"type": "histogram", "key": CheckFindingKey.VISIBLE_SPACES.value},
        {"type": "count", "key": "future_key", "count": 3},
    ]

    assert CapabilityCheckResult.model_validate(raw).findings == [_USERS]


def test_options_are_capped() -> None:
    with pytest.raises(ValidationError):
        OptionsFinding(
            key=CheckFindingKey.VISIBLE_SPACES,
            options=[
                FindingOption(value=str(i), label=str(i))
                for i in range(MAX_FINDING_OPTIONS + 1)
            ],
        )


def test_findings_reach_the_draft_state_and_back_from_the_cache() -> None:
    check: _FindingsCheck = _FindingsCheck(lambda _context: None)
    state: DraftCheckState = DraftCheckState(
        check_id=check.check_id,
        display_name=check.display_name,
        capability=check.capability,
        required=check.required,
        state=DraftCheckStateKind.PENDING,
    )

    apply_check_result(state, _result([_SPACES]))
    assert state.findings == [_SPACES]

    cached: CachedDraftResult = CachedDraftResult.model_validate_json(
        CachedDraftResult(
            state=DraftCheckStateKind.PASSED,
            message="",
            duration_ms=5,
            findings=[_USERS],
        ).model_dump_json()
    )
    apply_cached_result(state, cached)
    assert state.findings == [_USERS]
    # Creation writes the pair's report from cached draft results.
    assert cached_check_result(check, cached).findings == [_USERS]
