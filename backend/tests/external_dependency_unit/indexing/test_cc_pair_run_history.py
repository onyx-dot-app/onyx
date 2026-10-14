"""Coverage for a pair's run history beyond its attempts: prunes and connector
check runs join the run feed with their own statuses and errors, the check-run
lifecycle writes one history row per run, releasing the indexing hold lets the
first attempt start until a later check run, and scheduled checks come due on
the connector's check frequency."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.capability_checks import tasks as check_tasks
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.capability_checks import indexing_hold
from onyx.connectors.capability_checks.indexing_hold import get_first_indexing_hold
from onyx.connectors.capability_checks.indexing_hold_models import (
    IndexingHoldReason,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CheckFindingKey,
    CredentialCapabilityReport,
    FindingOption,
    OptionsFinding,
)
from onyx.connectors.capability_checks.registry import has_named_capability_checks
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.models import InputType
from onyx.db.connector import update_connector
from onyx.db.connector_credential_pair import get_cc_pairs_with_check_schedule
from onyx.db.credential_capability import (
    STALE_RUN_ERROR,
    delete_capability_check_runs_older_than,
    mark_capability_report_running,
    mark_capability_run_failed,
    mark_stale_capability_runs_failed,
    upsert_completed_capability_report,
)
from onyx.db.engine.time_utils import get_db_current_time
from onyx.db.enums import (
    AccessType,
    CapabilityCheckRunStatus,
    CapabilityCheckTrigger,
    CCPairRunErrors,
    CCPairRunKind,
    CCPairRunStatusGroup,
    ConnectorCredentialPairStatus,
    SyncStatus,
    SyncType,
)
from onyx.db.models import (
    CapabilityCheckRun,
    Connector,
    ConnectorCredentialPair,
    Credential,
    SyncRecord,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents import cc_pair as cc_pair_routes
from onyx.server.documents.cc_pair import get_cc_pair_runs, release_indexing_hold
from onyx.server.documents.models import (
    CCPairRunsResponse,
    ConnectorSnapshot,
    ConnectorUpdateRequest,
)
from tests.external_dependency_unit.conftest import create_test_user

# The sync kinds come from the EE-only sync_params helpers.
pytestmark = pytest.mark.usefixtures("enable_ee")

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
# A source with named checks, so its pairs run them.
_SOURCE = DocumentSource.CONFLUENCE
_CONFIG = {"wiki_base": "https://example.atlassian.net/wiki"}


def _create_cc_pair(
    db_session: Session, check_freq: int | None = None
) -> ConnectorCredentialPair:
    owner = create_test_user(db_session, "history_owner")
    connector = Connector(
        name="History Test Connector",
        source=_SOURCE,
        input_type=InputType.POLL,
        connector_specific_config=_CONFIG,
        refresh_freq=None,
        # Scheduled to prune, so the feed lists the pruning kind.
        prune_freq=86400,
        check_freq=check_freq,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=owner.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="History Test Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.commit()
    return cc_pair


def _prune(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: SyncStatus,
    docs_removed: int = 0,
    error_message: str | None = None,
) -> SyncRecord:
    record = SyncRecord(
        entity_id=cc_pair.id,
        sync_type=SyncType.PRUNING,
        sync_status=status,
        num_docs_synced=docs_removed,
        sync_start_time=_T0 + timedelta(minutes=minutes),
        sync_end_time=(
            None
            if status == SyncStatus.IN_PROGRESS
            else _T0 + timedelta(minutes=minutes + 1)
        ),
        error_message=error_message,
    )
    db_session.add(record)
    db_session.commit()
    return record


def _report(
    cc_pair: ConnectorCredentialPair, required_failed: bool
) -> CredentialCapabilityReport:
    return CredentialCapabilityReport(
        credential_id=cc_pair.credential_id,
        source=_SOURCE,
        connector_id=cc_pair.connector_id,
        checked_at=_T0,
        trigger=CapabilityCheckTrigger.MANUAL,
        verdicts={},
        check_results=[
            CapabilityCheckResult(
                capability=CredentialCapability.INDEXING,
                check_id="scopes",
                display_name="Check connector scopes",
                required=True,
                status=(
                    CapabilityCheckStatus.FAILED
                    if required_failed
                    else CapabilityCheckStatus.PASSED
                ),
                message="No page read access" if required_failed else "",
                # Hidden from the response when the findings switch is off,
                # so the feed search must not reach it.
                findings=[
                    OptionsFinding(
                        key=CheckFindingKey.VISIBLE_SPACES,
                        options=[FindingOption(value="HIDDEN1", label="Hidden space")],
                    )
                ],
            )
        ],
    )


def _check_run(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    minutes: int,
    status: CapabilityCheckRunStatus,
    report: CredentialCapabilityReport | None = None,
    error_message: str | None = None,
) -> CapabilityCheckRun:
    run = CapabilityCheckRun(
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        run_id=uuid4(),
        trigger=CapabilityCheckTrigger.SCHEDULED,
        status=status,
        report=report.model_dump(mode="json") if report is not None else None,
        error_message=error_message,
    )
    db_session.add(run)
    db_session.flush()
    run.time_created = _T0 + timedelta(minutes=minutes)
    db_session.commit()
    return run


def _runs(
    db_session: Session,
    user: User,
    cc_pair: ConnectorCredentialPair,
    kinds: list[CCPairRunKind] | None = None,
    q: str | None = None,
    errors: CCPairRunErrors | None = None,
) -> CCPairRunsResponse:
    return get_cc_pair_runs(
        cc_pair_id=cc_pair.id,
        page_num=0,
        page_size=10,
        since=None,
        kinds=kinds,
        status_groups=None,
        q=q,
        errors=errors,
        user=user,
        db_session=db_session,
    )


def _order(response: CCPairRunsResponse) -> list[tuple[CCPairRunKind, int]]:
    return [(run.kind, run.attempt.id) for run in response.items]


def _history(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> list[CapabilityCheckRun]:
    return (
        db_session.query(CapabilityCheckRun)
        .filter(
            CapabilityCheckRun.credential_id == cc_pair.credential_id,
            CapabilityCheckRun.connector_id == cc_pair.connector_id,
        )
        .order_by(CapabilityCheckRun.id)
        .all()
    )


def test_prunes_and_check_runs_join_the_feed(db_session: Session) -> None:
    assert has_named_capability_checks(_SOURCE)
    admin = create_test_user(db_session, "history_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session)
    prune_0 = _prune(db_session, cc_pair, 0, SyncStatus.SUCCESS, docs_removed=5)
    check_1 = _check_run(
        db_session,
        cc_pair,
        1,
        CapabilityCheckRunStatus.PASSED,
        report=_report(cc_pair, required_failed=False),
    )
    prune_2 = _prune(
        db_session, cc_pair, 2, SyncStatus.FAILED, error_message="quota exceeded"
    )
    check_3 = _check_run(
        db_session,
        cc_pair,
        3,
        CapabilityCheckRunStatus.FAILED_TO_RUN,
        error_message="broker down",
    )
    check_4 = _check_run(db_session, cc_pair, 4, CapabilityCheckRunStatus.RUNNING)

    everything = _runs(db_session, admin, cc_pair)
    prunes = _runs(db_session, admin, cc_pair, kinds=[CCPairRunKind.PRUNING])
    by_prune_error = _runs(db_session, admin, cc_pair, q="quota")
    by_check_error = _runs(db_session, admin, cc_pair, q="broker")
    # A completed run's check messages live in its report.
    by_check_report = _runs(db_session, admin, cc_pair, q="connector scopes")
    by_finding = _runs(db_session, admin, cc_pair, q="Hidden space")
    with_doc_errors = _runs(
        db_session, admin, cc_pair, errors=CCPairRunErrors.UNRESOLVED
    )

    assert everything.kinds == [
        CCPairRunKind.INDEXING,
        CCPairRunKind.PRUNING,
        CCPairRunKind.CHECKS,
    ]
    assert _order(everything) == [
        (CCPairRunKind.CHECKS, check_4.id),
        (CCPairRunKind.CHECKS, check_3.id),
        (CCPairRunKind.PRUNING, prune_2.id),
        (CCPairRunKind.CHECKS, check_1.id),
        (CCPairRunKind.PRUNING, prune_0.id),
    ]
    assert everything.status_counts == {
        CCPairRunStatusGroup.RUNNING: 1,
        CCPairRunStatusGroup.SUCCEEDED: 2,
        CCPairRunStatusGroup.FAILED: 2,
        CCPairRunStatusGroup.CANCELED: 0,
    }
    oldest_prune = everything.items[-1]
    assert oldest_prune.kind == CCPairRunKind.PRUNING
    assert oldest_prune.attempt.docs_removed == 5
    passed_run = everything.items[3]
    assert passed_run.kind == CCPairRunKind.CHECKS
    assert [result.check_id for result in passed_run.attempt.check_results] == [
        "scopes"
    ]
    assert _order(prunes) == [
        (CCPairRunKind.PRUNING, prune_2.id),
        (CCPairRunKind.PRUNING, prune_0.id),
    ]
    assert _order(by_prune_error) == [(CCPairRunKind.PRUNING, prune_2.id)]
    assert _order(by_check_error) == [(CCPairRunKind.CHECKS, check_3.id)]
    assert _order(by_check_report) == [(CCPairRunKind.CHECKS, check_1.id)]
    # A stored finding is not searchable: it can be hidden from the response.
    assert _order(by_finding) == []
    # Neither kind records document errors.
    assert _order(with_doc_errors) == []


def test_check_run_lifecycle_writes_one_history_row_per_run(
    db_session: Session,
) -> None:
    cc_pair = _create_cc_pair(db_session)
    config_hash = compute_connector_config_hash(_CONFIG)

    first = mark_capability_report_running(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=_SOURCE,
        trigger=CapabilityCheckTrigger.MANUAL,
        active_within=timedelta(hours=1),
    )
    db_session.commit()
    assert first is not None and first.run_id is not None
    (opened,) = _history(db_session, cc_pair)
    assert opened.run_id == first.run_id
    assert opened.status == CapabilityCheckRunStatus.RUNNING
    assert opened.trigger == CapabilityCheckTrigger.MANUAL

    upsert_completed_capability_report(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=_SOURCE,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(cc_pair, required_failed=True),
        connector_config_hash=config_hash,
        run_id=first.run_id,
    )
    db_session.commit()
    db_session.refresh(opened)
    assert opened.status == CapabilityCheckRunStatus.FAILED
    assert opened.time_finished is not None
    assert opened.report is not None
    assert opened.report["check_results"][0]["check_id"] == "scopes"

    second = mark_capability_report_running(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=_SOURCE,
        trigger=CapabilityCheckTrigger.SCHEDULED,
        active_within=timedelta(hours=1),
    )
    db_session.commit()
    assert second is not None
    mark_capability_run_failed(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        run_id=second.run_id,
        error_message="broker down",
    )
    db_session.commit()
    _, broken = _history(db_session, cc_pair)
    assert broken.run_id == second.run_id
    assert broken.status == CapabilityCheckRunStatus.FAILED_TO_RUN
    assert broken.error_message == "broker down"

    third = mark_capability_report_running(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=_SOURCE,
        trigger=CapabilityCheckTrigger.MANUAL,
        active_within=timedelta(hours=1),
    )
    db_session.commit()
    assert third is not None
    retired = mark_stale_capability_runs_failed(
        db_session, source=_SOURCE, stale_after=timedelta(seconds=0)
    )
    db_session.commit()
    # The shared database can hold other stale runs of the source.
    assert retired >= 1
    _, _, stale = _history(db_session, cc_pair)
    assert stale.status == CapabilityCheckRunStatus.FAILED_TO_RUN
    assert stale.error_message == STALE_RUN_ERROR
    # The retired run was merely slow: its result lands, as it does on the
    # report row.
    upsert_completed_capability_report(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=_SOURCE,
        trigger=CapabilityCheckTrigger.MANUAL,
        report=_report(cc_pair, required_failed=False),
        connector_config_hash=config_hash,
        run_id=third.run_id,
    )
    db_session.commit()
    db_session.refresh(stale)
    assert stale.status == CapabilityCheckRunStatus.PASSED
    assert stale.error_message is None


def test_release_lets_the_first_attempt_start_until_a_later_run(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(indexing_hold, "CONNECTOR_CHECKS_ENABLED", True)
    send_task = MagicMock()
    monkeypatch.setattr(cc_pair_routes.client_app, "send_task", send_task)
    admin = create_test_user(db_session, "history_admin", is_admin=True)
    cc_pair = _create_cc_pair(db_session)

    with pytest.raises(OnyxError) as not_held:
        release_indexing_hold(cc_pair_id=cc_pair.id, user=admin, db_session=db_session)
    assert not_held.value.error_code == OnyxErrorCode.INVALID_INPUT

    upsert_completed_capability_report(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=_SOURCE,
        trigger=CapabilityCheckTrigger.CC_PAIR_VALIDATION,
        report=_report(cc_pair, required_failed=True),
        connector_config_hash=compute_connector_config_hash(_CONFIG),
    )
    db_session.commit()
    held = get_first_indexing_hold(db_session, cc_pair)
    assert held is not None
    assert held.reason == IndexingHoldReason.REQUIRED_CHECKS_FAILED

    release_indexing_hold(cc_pair_id=cc_pair.id, user=admin, db_session=db_session)

    db_session.refresh(cc_pair)
    assert cc_pair.indexing_hold_released_at is not None
    assert get_first_indexing_hold(db_session, cc_pair) is None
    send_task.assert_called_once()

    # A run started after the release holds again.
    running = mark_capability_report_running(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=_SOURCE,
        trigger=CapabilityCheckTrigger.MANUAL,
        active_within=timedelta(hours=1),
    )
    db_session.commit()
    assert running is not None
    held_again = get_first_indexing_hold(db_session, cc_pair)
    assert held_again is not None
    assert held_again.reason == IndexingHoldReason.CHECKS_RUNNING


def test_scheduled_checks_come_due_on_the_check_frequency(
    db_session: Session,
) -> None:
    cc_pair = _create_cc_pair(db_session, check_freq=3600)
    unscheduled = _create_cc_pair(db_session)
    now = get_db_current_time(db_session)
    cc_pair.connector.time_created = now - timedelta(hours=2)
    db_session.commit()
    # The page reads the schedule from the connector snapshot.
    assert (
        ConnectorSnapshot.from_connector_db_model(cc_pair.connector).check_freq == 3600
    )

    scheduled = get_cc_pairs_with_check_schedule(db_session)
    assert cc_pair.id in {pair.id for pair in scheduled}
    assert unscheduled.id not in {pair.id for pair in scheduled}
    assert check_tasks._checks_due(db_session, cc_pair, now)
    assert not check_tasks._checks_due(db_session, unscheduled, now)

    # A run that started just now resets the clock.
    db_session.add(
        CapabilityCheckRun(
            credential_id=cc_pair.credential_id,
            connector_id=cc_pair.connector_id,
            run_id=uuid4(),
            trigger=CapabilityCheckTrigger.SCHEDULED,
            status=CapabilityCheckRunStatus.RUNNING,
        )
    )
    db_session.commit()
    assert not check_tasks._checks_due(db_session, cc_pair, now)

    cc_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()
    assert cc_pair.id not in {
        pair.id for pair in get_cc_pairs_with_check_schedule(db_session)
    }


def test_update_request_keeps_an_omitted_check_schedule(db_session: Session) -> None:
    cc_pair = _create_cc_pair(db_session, check_freq=3600)
    connector = cc_pair.connector

    fields = {
        "name": connector.name,
        "source": connector.source,
        "input_type": connector.input_type,
        "connector_specific_config": connector.connector_specific_config,
        "access_type": AccessType.PUBLIC,
    }

    # A request without the field (Terraform's upsert, the file upload path) keeps the schedule.
    omitted = ConnectorUpdateRequest.model_validate(fields)
    update_connector(connector.id, omitted.to_connector_base(), db_session)
    assert connector.check_freq == 3600

    # An explicit null clears it.
    cleared = ConnectorUpdateRequest.model_validate({**fields, "check_freq": None})
    update_connector(connector.id, cleared.to_connector_base(), db_session)
    assert connector.check_freq is None


def test_retention_deletes_only_old_finished_check_runs(db_session: Session) -> None:
    cc_pair = _create_cc_pair(db_session)
    old = _check_run(db_session, cc_pair, 0, CapabilityCheckRunStatus.PASSED)
    recent = _check_run(db_session, cc_pair, 1, CapabilityCheckRunStatus.PASSED)
    stuck = _check_run(db_session, cc_pair, 2, CapabilityCheckRunStatus.RUNNING)
    now = get_db_current_time(db_session)
    old.time_finished = now - timedelta(days=100)
    recent.time_finished = now - timedelta(days=1)
    stuck.time_created = now - timedelta(days=100)
    db_session.commit()

    deleted = delete_capability_check_runs_older_than(
        db_session, retain_for=timedelta(days=90)
    )

    assert deleted == 1
    remaining = {run.id for run in db_session.scalars(select(CapabilityCheckRun)).all()}
    assert old.id not in remaining
    assert {recent.id, stuck.id} <= remaining
