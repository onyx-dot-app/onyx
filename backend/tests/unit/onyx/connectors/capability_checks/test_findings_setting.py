from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks import findings_setting
from onyx.connectors.capability_checks.draft_runs import (
    CachedDraftResult,
    DraftCheckState,
    DraftCheckStateKind,
    apply_cached_result,
    cached_check_result,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckFinding,
    CheckFindingKey,
    CountFinding,
    CredentialCapabilityReport,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.db.enums import CapabilityCheckTrigger, CapabilityReportRunStatus
from onyx.db.models import CredentialCapabilityReportRow
from onyx.server.documents.credential_capabilities import CapabilityReportSnapshot
from onyx.server.security.store import _build_env_defaults

_USERS = CountFinding(key=CheckFindingKey.IMPERSONATABLE_USERS, count=12)


class _UsersCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="users_check",
            display_name="Users check",
            requires_connector_instance=False,
        )

    def run(
        self,
        context: CapabilityCheckContext,  # noqa: ARG002
    ) -> list[CheckFinding] | None:
        return [_USERS]


@pytest.fixture
def findings_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        findings_setting,
        "get_security_settings",
        lambda: MagicMock(allow_connector_check_findings=False),
    )


def _context() -> CapabilityCheckContext:
    return CapabilityCheckContext(source=DocumentSource.CONFLUENCE, credential_json={})


def _cached() -> CachedDraftResult:
    return CachedDraftResult(
        state=DraftCheckStateKind.PASSED,
        message="",
        duration_ms=1,
        findings=[_USERS],
    )


def test_findings_are_on_by_default() -> None:
    assert _build_env_defaults().allow_connector_check_findings is True
    assert run_capability_checks([_UsersCheck()], _context())[0].findings == [_USERS]


@pytest.mark.usefixtures("findings_off")
def test_with_findings_off_the_runner_keeps_none() -> None:
    result: CapabilityCheckResult = run_capability_checks([_UsersCheck()], _context())[
        0
    ]

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.findings == []


def test_findings_turned_off_during_a_run_are_not_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enabled: list[bool] = [True, False]
    monkeypatch.setattr(
        findings_setting,
        "get_security_settings",
        lambda: MagicMock(allow_connector_check_findings=enabled.pop(0)),
    )
    second: _UsersCheck = _UsersCheck()
    second.check_id = "users_check_2"

    results: list[CapabilityCheckResult] = run_capability_checks(
        [_UsersCheck(), second], _context()
    )

    assert [result.findings for result in results] == [[_USERS], []]


@pytest.mark.usefixtures("findings_off")
def test_with_findings_off_cached_findings_are_not_reused() -> None:
    check: _UsersCheck = _UsersCheck()
    state: DraftCheckState = DraftCheckState(
        check_id=check.check_id,
        display_name=check.display_name,
        capability=check.capability,
        required=check.required,
        state=DraftCheckStateKind.PENDING,
    )

    apply_cached_result(state, _cached())

    assert state.findings == []
    # Creation would otherwise store them in the pair's report.
    assert cached_check_result(check, _cached()).findings == []


@pytest.mark.usefixtures("findings_off")
def test_with_findings_off_a_stored_report_is_returned_without_them() -> None:
    report: CredentialCapabilityReport = CredentialCapabilityReport(
        credential_id=1,
        source=DocumentSource.CONFLUENCE,
        checked_at=datetime.now(timezone.utc),
        trigger=CapabilityCheckTrigger.MANUAL,
        verdicts={},
        check_results=[
            CapabilityCheckResult(
                capability=CredentialCapability.INDEXING,
                check_id="users_check",
                display_name="Users check",
                required=True,
                status=CapabilityCheckStatus.PASSED,
                findings=[_USERS],
            )
        ],
    )
    row: CredentialCapabilityReportRow = CredentialCapabilityReportRow(
        credential_id=1,
        connector_id=None,
        source=DocumentSource.CONFLUENCE,
        trigger=CapabilityCheckTrigger.MANUAL,
        run_status=CapabilityReportRunStatus.COMPLETED,
        report=report.model_dump(mode="json"),
        time_updated=datetime.now(timezone.utc),
    )

    snapshot: CapabilityReportSnapshot = CapabilityReportSnapshot.from_row(row)

    assert snapshot.report is not None
    assert snapshot.report.check_results[0].findings == []
