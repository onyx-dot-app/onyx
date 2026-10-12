from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks import draft_runs, findings_setting
from onyx.connectors.capability_checks.draft_runs import (
    DraftCheckRunSnapshot,
    DraftCheckState,
    DraftCheckStateKind,
    DraftRunStatus,
    StoredDraftRun,
    apply_cached_result,
    apply_check_result,
    cache_draft_result,
    cached_check_result,
    decide_draft_check_state,
    get_cached_draft_result,
)
from onyx.connectors.capability_checks.models import (
    MAX_ADVISORY_LENGTH,
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CapabilityVerdict,
    CheckAdvisory,
    CheckFindingKey,
    CheckNotApplicableError,
    CheckOutput,
    CountFinding,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.exceptions import ConnectorValidationError

_EMPTY_CHANNEL = CheckAdvisory(
    message="#general is empty; thread reads were not verified."
)


class _AdvisingCheck(CapabilityCheck):
    def __init__(self, *, fails: bool = False, is_fallback: bool = False) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="history_read",
            display_name="History read",
            requires_connector_instance=False,
            is_fallback=is_fallback,
        )
        self._fails = fails

    def run(
        self,
        context: CapabilityCheckContext,  # noqa: ARG002
    ) -> CheckOutput | None:
        if self._fails:
            raise ConnectorValidationError("missing_scope: channels:history")
        return CheckOutput(
            findings=[CountFinding(key=CheckFindingKey.READABLE_CHANNELS, count=1)],
            advisories=[_EMPTY_CHANNEL],
        )


def _context() -> CapabilityCheckContext:
    return CapabilityCheckContext(source=DocumentSource.SLACK, credential_json={})


def _state(
    capability: CredentialCapability,
    state: DraftCheckStateKind,
    *,
    required: bool = True,
) -> DraftCheckState:
    return DraftCheckState(
        check_id=f"{capability.value}_{state.value}",
        display_name="check",
        capability=capability,
        required=required,
        state=state,
    )


def _snapshot(checks: list[DraftCheckState]) -> DraftCheckRunSnapshot:
    return DraftCheckRunSnapshot(
        run_id=uuid4(),
        draft_key="draft",
        source=DocumentSource.SLACK,
        credential_id=1,
        access_type=None,
        status=DraftRunStatus.RUNNING,
        form_errors={},
        unknown_fields=[],
        checks=checks,
    )


def test_a_passing_check_reports_its_advisories() -> None:
    result: CapabilityCheckResult = run_capability_checks(
        [_AdvisingCheck()], _context()
    )[0]

    assert result.status == CapabilityCheckStatus.PASSED
    assert result.advisories == [_EMPTY_CHANNEL]


def test_turning_findings_off_keeps_advisories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        findings_setting,
        "get_security_settings",
        lambda: MagicMock(allow_connector_check_findings=False),
    )

    result: CapabilityCheckResult = run_capability_checks(
        [_AdvisingCheck()], _context()
    )[0]

    assert result.findings == []
    assert result.advisories == [_EMPTY_CHANNEL]


def test_a_long_advisory_is_shortened() -> None:
    advisory = CheckAdvisory(message="x" * (MAX_ADVISORY_LENGTH * 2))

    assert len(advisory.message) == MAX_ADVISORY_LENGTH
    assert advisory.message.endswith("…")


def test_a_draft_state_carries_advisories_error_type_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store: dict[str, bytes] = {}
    cache = MagicMock()
    cache.set.side_effect = lambda key, value, ex: store.__setitem__(  # noqa: ARG005
        key, value.encode()
    )
    cache.get.side_effect = store.get
    monkeypatch.setattr(draft_runs, "get_cache_backend", lambda: cache)

    for check in (_AdvisingCheck(is_fallback=True), _AdvisingCheck(fails=True)):
        state: DraftCheckState = decide_draft_check_state(check, _context())
        result = run_capability_checks([check], _context())[0]
        apply_check_result(state, result)
        cache_draft_result(check.check_id, result)
        cached_state: DraftCheckState = decide_draft_check_state(check, _context())
        cached = get_cached_draft_result(check.check_id)
        assert cached is not None
        apply_cached_result(cached_state, cached)

        for current in (state, cached_state):
            assert current.is_fallback == check.is_fallback
            assert current.error_type == result.error_type
            assert current.advisories == result.advisories
        store.clear()

    assert result.error_type == "ConnectorValidationError"


def test_draft_verdicts_cover_only_finished_capabilities() -> None:
    snapshot: DraftCheckRunSnapshot = _snapshot(
        [
            _state(CredentialCapability.INDEXING, DraftCheckStateKind.PASSED),
            _state(
                CredentialCapability.INDEXING,
                DraftCheckStateKind.FAILED,
                required=False,
            ),
            _state(
                CredentialCapability.DOC_PERMISSION_SYNC, DraftCheckStateKind.RUNNING
            ),
        ]
    )

    verdicts = snapshot.verdicts

    assert verdicts[CredentialCapability.INDEXING] == (
        CapabilityVerdict.PASSED_WITH_WARNINGS
    )
    assert CredentialCapability.DOC_PERMISSION_SYNC not in verdicts


def test_a_waiting_required_check_leaves_its_capability_unverified() -> None:
    snapshot: DraftCheckRunSnapshot = _snapshot(
        [
            _state(CredentialCapability.INDEXING, DraftCheckStateKind.PASSED),
            _state(CredentialCapability.INDEXING, DraftCheckStateKind.WAITING),
            _state(CredentialCapability.INDEXING, DraftCheckStateKind.NOT_APPLICABLE),
        ]
    )

    assert snapshot.verdicts[CredentialCapability.INDEXING] == (
        CapabilityVerdict.SKIPPED
    )


def test_a_stored_run_with_verdicts_reads_back() -> None:
    run = StoredDraftRun(
        user_id=uuid4(),
        snapshot=_snapshot(
            [_state(CredentialCapability.INDEXING, DraftCheckStateKind.PASSED)]
        ),
        result_cache_keys={},
    )

    raw: str = run.model_dump_json()

    assert '"verdicts"' in raw
    assert StoredDraftRun.model_validate_json(raw) == run


class _OffGridCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="grid_scope",
            display_name="Grid scope",
            requires_connector_instance=False,
        )

    def run(
        self,
        context: CapabilityCheckContext,  # noqa: ARG002
    ) -> CheckOutput | None:
        raise CheckNotApplicableError("The workspace is not on Enterprise Grid.")


def test_a_check_that_does_not_apply_at_run_time_is_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store: dict[str, bytes] = {}
    cache = MagicMock()
    cache.set.side_effect = lambda key, value, ex: store.__setitem__(  # noqa: ARG005
        key, value.encode()
    )
    cache.get.side_effect = store.get
    monkeypatch.setattr(draft_runs, "get_cache_backend", lambda: cache)
    check = _OffGridCheck()

    result = run_capability_checks([check], _context())[0]
    state: DraftCheckState = decide_draft_check_state(check, _context())
    apply_check_result(state, result)
    cache_draft_result("grid", result)
    cached = get_cached_draft_result("grid")

    assert result.status == CapabilityCheckStatus.SKIPPED
    assert result.applicable is False
    assert state.state == DraftCheckStateKind.NOT_APPLICABLE
    assert cached is not None
    assert cached.state == DraftCheckStateKind.NOT_APPLICABLE
    reused = cached_check_result(check, cached)
    assert reused.status == CapabilityCheckStatus.SKIPPED
    assert reused.applicable is False


def test_a_skipped_discovery_check_stays_skipped_in_a_draft() -> None:
    state = DraftCheckState(
        check_id="listing",
        display_name="listing",
        capability=CredentialCapability.INDEXING,
        required=False,
        state=DraftCheckStateKind.RUNNING,
        discovery=True,
    )
    skipped = CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id="listing",
        display_name="listing",
        required=False,
        status=CapabilityCheckStatus.SKIPPED,
        applicable=False,
        discovery=True,
    )

    apply_check_result(state, skipped)

    assert state.state == DraftCheckStateKind.SKIPPED
