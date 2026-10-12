from datetime import datetime, timezone
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
    cache_draft_result,
    pending_in_run_order,
    required_check_failed,
)
from onyx.connectors.capability_checks.findings import bounded_options
from onyx.connectors.capability_checks.models import (
    MAX_FINDING_TEXT_LENGTH,
    CapabilityCheck,
    CapabilityCheckContext,
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckFinding,
    CheckFindingKey,
    CountFinding,
    OptionsFinding,
    parse_known_findings,
)
from onyx.connectors.capability_checks.runner import run_capability_checks
from onyx.connectors.edit_plan.models import (
    EditPlan,
    ProposedPairState,
    StoredEditPlan,
)
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.server.documents.connector_edit_models import ConnectorEditPlanResponse

_USERS: CountFinding = CountFinding(key=CheckFindingKey.IMPERSONATABLE_USERS, count=4)


class _Check(CapabilityCheck):
    def __init__(
        self,
        check_id: str,
        findings: list[CheckFinding] | None = None,
        *,
        discovery: bool = False,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=check_id,
            requires_connector_instance=False,
            discovery=discovery,
        )
        self._findings = findings

    def run(
        self,
        context: CapabilityCheckContext,  # noqa: ARG002
    ) -> list[CheckFinding] | None:
        return self._findings


def _context(
    source: DocumentSource = DocumentSource.CONFLUENCE,
) -> CapabilityCheckContext:
    return CapabilityCheckContext(source=source, credential_json={})


def _state(
    check_id: str,
    state: DraftCheckStateKind,
    *,
    required: bool = True,
    discovery: bool = False,
) -> DraftCheckState:
    return DraftCheckState(
        check_id=check_id,
        display_name=check_id,
        capability=CredentialCapability.INDEXING,
        required=required,
        state=state,
        discovery=discovery,
    )


def _snapshot(checks: list[DraftCheckState]) -> DraftCheckRunSnapshot:
    return DraftCheckRunSnapshot(
        run_id=uuid4(),
        draft_key="draft",
        source=DocumentSource.CONFLUENCE,
        credential_id=1,
        access_type=None,
        status=DraftRunStatus.RUNNING,
        form_errors={},
        unknown_fields=[],
        checks=checks,
    )


def _result(status: CapabilityCheckStatus, *, discovery: bool) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id="listing",
        display_name="listing",
        required=False,
        status=status,
        discovery=discovery,
    )


def test_a_skipped_discovery_result_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache: MagicMock = MagicMock()
    monkeypatch.setattr(draft_runs, "get_cache_backend", lambda: cache)

    cache_draft_result("k1", _result(CapabilityCheckStatus.SKIPPED, discovery=True))
    assert cache.set.call_count == 0

    # A validation skip and a passed listing are still cached.
    cache_draft_result("k2", _result(CapabilityCheckStatus.SKIPPED, discovery=False))
    cache_draft_result("k3", _result(CapabilityCheckStatus.PASSED, discovery=True))
    assert cache.set.call_count == 2


def test_a_cached_required_failure_skips_discovery() -> None:
    results: list[CapabilityCheckResult] = run_capability_checks(
        [_Check("listing", [_USERS], discovery=True)],
        _context(),
        required_check_failed=True,
    )

    assert results[0].status == CapabilityCheckStatus.SKIPPED
    assert results[0].findings == []


def test_a_draft_snapshot_knows_its_cached_required_failures() -> None:
    assert required_check_failed(
        _snapshot([_state("auth", DraftCheckStateKind.FAILED)])
    )
    assert not required_check_failed(
        _snapshot([_state("comments", DraftCheckStateKind.FAILED, required=False)])
    )


def test_pending_checks_run_validation_first_whatever_the_registration() -> None:
    snapshot: DraftCheckRunSnapshot = _snapshot(
        [
            _state("auth", DraftCheckStateKind.PASSED),
            _state("listing", DraftCheckStateKind.PENDING, discovery=True),
            _state("content", DraftCheckStateKind.PENDING),
        ]
    )

    assert [check.check_id for check in pending_in_run_order(snapshot)] == [
        "content",
        "listing",
    ]


def test_a_finding_for_a_field_the_config_lacks_is_dropped() -> None:
    misnamed: OptionsFinding = OptionsFinding(
        key=CheckFindingKey.VISIBLE_SPACES, field_name="no_such_field", options=[]
    )

    results: list[CapabilityCheckResult] = run_capability_checks(
        [_Check("listing", [misnamed, _USERS], discovery=True)], _context()
    )

    assert results[0].findings == [_USERS]


def test_long_option_text_is_shortened_and_long_values_left_out() -> None:
    finding: OptionsFinding = bounded_options(
        iter(["ok", "x" * (MAX_FINDING_TEXT_LENGTH + 1)]),
        key=CheckFindingKey.VISIBLE_SPACES,
        field_name="space",
        value=lambda item: item,
        label=lambda item: item * 600,
    )

    assert [option.value for option in finding.options] == ["ok"]
    assert len(finding.options[0].label) == MAX_FINDING_TEXT_LENGTH


def test_unparseable_findings_read_as_none() -> None:
    assert parse_known_findings("not a list") == []


def test_the_plan_response_hides_findings_on_a_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        findings_setting,
        "get_security_settings",
        lambda: MagicMock(allow_connector_check_findings=False),
    )
    stored: StoredEditPlan = StoredEditPlan(
        plan_id=uuid4(),
        cc_pair_id=1,
        user_id=uuid4(),
        base_state_hash="hash",
        proposed=ProposedPairState(
            source=DocumentSource.CONFLUENCE,
            input_type=InputType.POLL,
            connector_specific_config={},
            access_type=AccessType.PUBLIC,
            credential_id=1,
            name="pair",
        ),
        plan=EditPlan(
            field_changes=[],
            changed_settings=[],
            steps=[],
            notes=[],
            dry_run_results=[
                _result(CapabilityCheckStatus.PASSED, discovery=True).model_copy(
                    update={"findings": [_USERS]}
                )
            ],
            indexed_document_count=0,
        ),
        created_at=datetime.now(timezone.utc),
    )

    response: ConnectorEditPlanResponse = ConnectorEditPlanResponse.from_stored(stored)

    assert response.plan.dry_run_results[0].findings == []
    assert stored.plan.dry_run_results[0].findings == [_USERS]
