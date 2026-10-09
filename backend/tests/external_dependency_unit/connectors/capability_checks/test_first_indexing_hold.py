"""The hold on a pair's first index attempt. Scheduling and "Run indexing"
create the attempt as usual; its docfetching task is sent only when the stored
report has no required check that is running, failed or failed to run."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docfetching.task_creation_utils import (
    try_creating_docfetching_task,
)
from onyx.background.celery.tasks.docprocessing.tasks import (
    _kickoff_indexing_tasks,
    fail_inconsistent_index_attempts,
)
from onyx.configs.constants import DocumentSource, OnyxCeleryTask
from onyx.connectors.capability_checks import indexing_hold
from onyx.connectors.capability_checks.indexing_hold import get_first_indexing_hold
from onyx.connectors.capability_checks.indexing_hold_models import (
    IndexingHoldReason,
)
from onyx.connectors.capability_checks.models import (
    CapabilityCheckResult,
    CapabilityCheckStatus,
    CredentialCapability,
    CredentialCapabilityReport,
)
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.db.credential_capability import (
    get_capability_report_row,
    mark_capability_report_running,
    mark_stale_capability_runs_failed,
    upsert_completed_capability_report,
)
from onyx.db.enums import (
    CapabilityCheckTrigger,
    ConnectorCredentialPairStatus,
    IndexingStatus,
    IndexModelStatus,
)
from onyx.db.index_attempt import (
    cc_pair_has_dispatched_index_attempts,
    get_stale_not_started_index_attempts,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    CredentialCapabilityReportRow,
    IndexAttempt,
    SearchSettings,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents import cc_pair as cc_pair_api
from onyx.server.documents import connector as connector_api
from onyx.server.documents.cc_pair import (
    get_cc_pair_full_info,
    update_cc_pair_status,
)
from onyx.server.documents.connector import trigger_indexing_for_cc_pair
from onyx.server.documents.models import CCStatusUpdateRequest
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_future_search_settings,
)

_TRIGGER = CapabilityCheckTrigger.CC_PAIR_VALIDATION


def _make_pair(db_session: Session, source: DocumentSource) -> ConnectorCredentialPair:
    cc_pair = make_cc_pair(db_session, source=source)
    # A new pair, with a refresh so a second attempt is due at once.
    cc_pair.status = ConnectorCredentialPairStatus.INITIAL_INDEXING
    cc_pair.connector.refresh_freq = 3600
    db_session.commit()
    return cc_pair


def _cleanup(db_session: Session, cc_pair: ConnectorCredentialPair) -> None:
    db_session.rollback()
    db_session.execute(
        delete(IndexAttempt).where(
            IndexAttempt.connector_credential_pair_id == cc_pair.id
        )
    )
    db_session.commit()
    cleanup_cc_pair(db_session, cc_pair)


@pytest.fixture(autouse=True)
def connector_checks_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexing_hold, "CONNECTOR_CHECKS_ENABLED", True)


@pytest.fixture
def slack_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = _make_pair(db_session, DocumentSource.SLACK)
    yield cc_pair
    _cleanup(db_session, cc_pair)


@pytest.fixture
def search_settings(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> SearchSettings:
    return get_current_search_settings(db_session)


class _Beat:
    """Runs the beat's kickoff for one pair. Celery sends are recorded, never
    made."""

    def __init__(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        self.db_session = db_session
        self.cc_pair = cc_pair
        self.search_settings = search_settings
        self.celery_app = MagicMock()

    def run(self) -> None:
        self.db_session.expire_all()
        _kickoff_indexing_tasks(
            celery_app=self.celery_app,
            db_session=self.db_session,
            search_settings=self.search_settings,
            cc_pair_ids=[self.cc_pair.id],
            secondary_index_building=False,
            redis_client=get_redis_client(),
            lock_beat=MagicMock(),
            tenant_id=get_current_tenant_id(),
        )

    def attempts(self) -> list[IndexAttempt]:
        self.db_session.expire_all()
        return list(
            self.db_session.scalars(
                select(IndexAttempt)
                .where(IndexAttempt.connector_credential_pair_id == self.cc_pair.id)
                .order_by(IndexAttempt.id)
            ).all()
        )

    def sent_attempt_ids(self) -> list[int]:
        return [
            call.kwargs["kwargs"]["index_attempt_id"]
            for call in self.celery_app.send_task.call_args_list
            if call.args[0] == OnyxCeleryTask.CONNECTOR_DOC_FETCHING_TASK
        ]

    def assert_waiting(self) -> IndexAttempt:
        attempts = self.attempts()
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.status == IndexingStatus.NOT_STARTED
        assert attempt.celery_task_id is None
        assert self.sent_attempt_ids() == []
        return attempt

    def assert_started(self) -> IndexAttempt:
        attempts = self.attempts()
        assert len(attempts) == 1
        attempt = attempts[0]
        assert attempt.celery_task_id is not None
        assert self.sent_attempt_ids() == [attempt.id]
        return attempt


@pytest.fixture
def beat(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
) -> _Beat:
    return _Beat(db_session, slack_pair, search_settings)


def _result(
    status: CapabilityCheckStatus,
    *,
    check_id: str = "slack_token",
    required: bool = True,
    is_fallback: bool = False,
) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=CredentialCapability.INDEXING,
        check_id=check_id,
        display_name=f"{check_id} display",
        required=required,
        status=status,
        message=f"{check_id} {status.value}",
        is_fallback=is_fallback,
        remediation="Reinstall the app.",
    )


def _mark_running(db_session: Session, cc_pair: ConnectorCredentialPair) -> None:
    row = mark_capability_report_running(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=cc_pair.connector.source,
        trigger=_TRIGGER,
        active_within=timedelta(0),
    )
    assert row is not None
    db_session.commit()


def _complete(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    results: list[CapabilityCheckResult],
) -> None:
    """Marks the row RUNNING and lands a completed report on it."""
    row = mark_capability_report_running(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=cc_pair.connector.source,
        trigger=_TRIGGER,
        active_within=timedelta(0),
    )
    assert row is not None
    upsert_completed_capability_report(
        db_session,
        credential_id=cc_pair.credential_id,
        connector_id=cc_pair.connector_id,
        source=cc_pair.connector.source,
        trigger=_TRIGGER,
        report=CredentialCapabilityReport(
            credential_id=cc_pair.credential_id,
            source=cc_pair.connector.source,
            connector_id=cc_pair.connector_id,
            checked_at=datetime.now(timezone.utc),
            trigger=_TRIGGER,
            verdicts={},
            check_results=results,
        ),
        connector_config_hash=compute_connector_config_hash(
            cc_pair.connector.connector_specific_config
        ),
        run_id=row.run_id,
    )
    db_session.commit()


def _hold_reason(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> IndexingHoldReason | None:
    db_session.expire_all()
    hold = get_first_indexing_hold(db_session, cc_pair)
    return hold.reason if hold is not None else None


def test_waits_while_checks_run(
    db_session: Session, slack_pair: ConnectorCredentialPair, beat: _Beat
) -> None:
    _mark_running(db_session, slack_pair)

    beat.run()
    beat.assert_waiting()
    assert _hold_reason(db_session, slack_pair) == IndexingHoldReason.CHECKS_RUNNING


def test_waits_on_a_failed_required_check(
    db_session: Session, slack_pair: ConnectorCredentialPair, beat: _Beat
) -> None:
    _complete(
        db_session,
        slack_pair,
        [
            _result(CapabilityCheckStatus.FAILED),
            _result(CapabilityCheckStatus.PASSED, check_id="slack_channels"),
            # A failed check that is not required does not hold.
            _result(
                CapabilityCheckStatus.FAILED, check_id="slack_optional", required=False
            ),
        ],
    )

    beat.run()
    beat.assert_waiting()
    hold = get_first_indexing_hold(db_session, slack_pair)
    assert hold is not None
    assert hold.reason == IndexingHoldReason.REQUIRED_CHECKS_FAILED
    assert [check.check_id for check in hold.failed_checks] == ["slack_token"]
    assert hold.failed_checks[0].message == "slack_token failed"
    assert hold.failed_checks[0].remediation == "Reinstall the app."


@pytest.mark.parametrize(
    "status", [CapabilityCheckStatus.INDETERMINATE, CapabilityCheckStatus.SKIPPED]
)
def test_starts_on_indeterminate_or_skipped(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    beat: _Beat,
    status: CapabilityCheckStatus,
) -> None:
    _complete(db_session, slack_pair, [_result(status)])

    beat.run()
    beat.assert_started()


def test_starts_without_a_report(beat: _Beat) -> None:
    beat.run()
    beat.assert_started()


def test_starts_for_a_source_without_named_checks(
    db_session: Session,
    search_settings: SearchSettings,
    tenant_context: None,  # noqa: ARG001
) -> None:
    cc_pair = _make_pair(db_session, DocumentSource.MOCK_CONNECTOR)
    try:
        _complete(
            db_session,
            cc_pair,
            [
                _result(
                    CapabilityCheckStatus.FAILED,
                    check_id="mock_connector_connector_settings",
                    is_fallback=True,
                )
            ],
        )
        beat = _Beat(db_session, cc_pair, search_settings)

        beat.run()
        beat.assert_started()
    finally:
        _cleanup(db_session, cc_pair)


def test_a_later_attempt_never_waits(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    beat: _Beat,
) -> None:
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])
    long_ago = datetime.now(timezone.utc) - timedelta(days=1)
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=slack_pair.id,
            search_settings_id=search_settings.id,
            from_beginning=True,
            status=IndexingStatus.FAILED,
            celery_task_id="earlier_task",
            time_updated=long_ago,
        )
    )
    db_session.commit()

    beat.run()
    later = beat.attempts()[-1]
    assert later.status == IndexingStatus.NOT_STARTED
    assert beat.sent_attempt_ids() == [later.id]


def test_a_waiting_attempt_ended_by_a_bulk_cancel_keeps_the_hold(
    db_session: Session, slack_pair: ConnectorCredentialPair, beat: _Beat
) -> None:
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])
    beat.run()
    waiting = beat.assert_waiting()

    # Same update as the index swap's cancel_indexing_attempts_for_search_settings.
    db_session.execute(
        update(IndexAttempt)
        .where(IndexAttempt.id == waiting.id)
        .values(status=IndexingStatus.FAILED)
    )
    db_session.commit()

    assert not cc_pair_has_dispatched_index_attempts(db_session, slack_pair.id)
    assert (
        _hold_reason(db_session, slack_pair)
        == IndexingHoldReason.REQUIRED_CHECKS_FAILED
    )


def test_starts_after_a_passing_rerun_without_duplicates(
    db_session: Session, slack_pair: ConnectorCredentialPair, beat: _Beat
) -> None:
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])
    beat.run()
    waiting = beat.assert_waiting()

    # Later beats keep the one waiting attempt.
    beat.run()
    assert beat.assert_waiting().id == waiting.id

    # The admin re-runs the checks after a fix.
    _mark_running(db_session, slack_pair)
    beat.run()
    beat.assert_waiting()

    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.PASSED)])
    beat.run()
    assert beat.assert_started().id == waiting.id

    # The task is sent once.
    beat.run()
    assert beat.assert_started().id == waiting.id


def test_a_dead_run_counts_as_failed_to_run(
    db_session: Session, slack_pair: ConnectorCredentialPair, beat: _Beat
) -> None:
    _mark_running(db_session, slack_pair)
    db_session.execute(
        update(CredentialCapabilityReportRow)
        .where(
            CredentialCapabilityReportRow.credential_id == slack_pair.credential_id,
            CredentialCapabilityReportRow.connector_id == slack_pair.connector_id,
        )
        .values(run_started_at=datetime.now(timezone.utc) - timedelta(days=7))
    )
    db_session.commit()

    # Stale before the sweep, and FAILED_TO_RUN after it: both hold.
    beat.run()
    beat.assert_waiting()
    assert (
        _hold_reason(db_session, slack_pair) == IndexingHoldReason.CHECKS_FAILED_TO_RUN
    )
    mark_stale_capability_runs_failed(
        db_session, source=DocumentSource.SLACK, stale_after=timedelta(days=1)
    )
    db_session.commit()
    beat.run()
    beat.assert_waiting()
    assert (
        _hold_reason(db_session, slack_pair) == IndexingHoldReason.CHECKS_FAILED_TO_RUN
    )

    # A passing re-run from the card releases it.
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.PASSED)])
    beat.run()
    beat.assert_started()


def test_manual_trigger_creates_an_attempt_that_waits(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    beat: _Beat,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connector_api.client_app, "send_task", MagicMock())
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])

    assert (
        trigger_indexing_for_cc_pair(
            [slack_pair.credential_id],
            slack_pair.connector_id,
            True,
            get_current_tenant_id(),
            db_session,
        )
        == 1
    )
    beat.run()
    waiting = beat.assert_waiting()
    assert waiting.from_beginning is True
    db_session.expire_all()
    # The beat consumed the trigger into the attempt.
    assert slack_pair.indexing_trigger is None

    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.PASSED)])
    beat.run()
    assert beat.assert_started().id == waiting.id


def test_a_waiting_attempt_is_not_cleaned_up_as_stuck(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    beat: _Beat,
) -> None:
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])
    beat.run()
    waiting = beat.assert_waiting()
    waiting.time_created = datetime.now(timezone.utc) - timedelta(days=2)
    db_session.commit()

    fail_inconsistent_index_attempts(db_session, MagicMock())
    assert beat.assert_waiting().id == waiting.id
    assert waiting.id not in {
        attempt.id
        for attempt in get_stale_not_started_index_attempts(
            db_session, datetime.now(timezone.utc)
        )
    }

    # An attempt without a task on a pair that already indexed is still failed.
    other = _make_pair(db_session, DocumentSource.SLACK)
    try:
        db_session.add_all(
            [
                IndexAttempt(
                    connector_credential_pair_id=other.id,
                    search_settings_id=search_settings.id,
                    from_beginning=True,
                    status=IndexingStatus.SUCCESS,
                    celery_task_id="earlier_task",
                ),
                IndexAttempt(
                    connector_credential_pair_id=other.id,
                    search_settings_id=search_settings.id,
                    from_beginning=False,
                    status=IndexingStatus.NOT_STARTED,
                ),
            ]
        )
        db_session.commit()

        fail_inconsistent_index_attempts(db_session, MagicMock())

        db_session.expire_all()
        statuses = db_session.scalars(
            select(IndexAttempt.status)
            .where(IndexAttempt.connector_credential_pair_id == other.id)
            .order_by(IndexAttempt.id)
        ).all()
        assert statuses == [IndexingStatus.SUCCESS, IndexingStatus.FAILED]
    finally:
        _cleanup(db_session, other)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "first_hold_admin", is_admin=True)
    yield user
    delete_test_user(db_session, user)
    db_session.commit()


def _set_status(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    status: ConnectorCredentialPairStatus,
    user: User,
) -> None:
    update_cc_pair_status(
        cc_pair.id,
        CCStatusUpdateRequest(status=status),
        user=user,
        db_session=db_session,
    )


def test_pause_ends_a_waiting_attempt_and_the_next_one_still_waits(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    beat: _Beat,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The status endpoint sends CHECK_FOR_INDEXING and revokes tasks; record
    # those calls instead of reaching the shared broker.
    monkeypatch.setattr(cc_pair_api, "client_app", MagicMock())
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])
    beat.run()
    waiting = beat.assert_waiting()

    # Pausing ends the waiting attempt at once; it stays undispatched.
    _set_status(db_session, slack_pair, ConnectorCredentialPairStatus.PAUSED, admin)
    (ended,) = beat.attempts()
    assert ended.id == waiting.id
    assert ended.status == IndexingStatus.CANCELED
    assert ended.celery_task_id is None
    assert not cc_pair_has_dispatched_index_attempts(db_session, slack_pair.id)

    # After a resume the next attempt still waits, and starts once the checks
    # pass. No task is sent for the canceled one. A resumed pair is ACTIVE, so
    # a zero refresh_freq lets the next beat create the attempt at once.
    _set_status(db_session, slack_pair, ConnectorCredentialPairStatus.ACTIVE, admin)
    slack_pair.connector.refresh_freq = 0
    db_session.commit()
    beat.run()
    first, second = beat.attempts()
    assert first.id == waiting.id
    assert second.status == IndexingStatus.NOT_STARTED
    assert second.celery_task_id is None
    assert beat.sent_attempt_ids() == []

    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.PASSED)])
    beat.run()
    beat.run()
    assert beat.sent_attempt_ids() == [second.id]


def test_a_beat_after_a_pause_neither_dispatches_nor_creates(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    beat: _Beat,
) -> None:
    """A beat that runs while the pause commits sees PAUSED under the creation
    lock: it does not send the waiting attempt's task, and it does not create a
    replacement attempt."""
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])
    beat.run()
    waiting = beat.assert_waiting()
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.PASSED)])

    # The pause's status lands before the waiting attempt is ended.
    slack_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()

    beat.run()
    assert beat.assert_waiting().id == waiting.id

    # Creation skips a PAUSED pair too, also when its waiting attempt is gone.
    db_session.execute(
        update(IndexAttempt)
        .where(IndexAttempt.id == waiting.id)
        .values(status=IndexingStatus.CANCELED)
    )
    db_session.commit()
    assert (
        try_creating_docfetching_task(
            beat.celery_app,
            slack_pair,
            search_settings,
            False,
            db_session,
            get_redis_client(),
            get_current_tenant_id(),
        )
        is None
    )
    assert [attempt.id for attempt in beat.attempts()] == [waiting.id]
    assert beat.sent_attempt_ids() == []


def test_an_unreadable_report_holds_as_failed_to_run(
    db_session: Session, slack_pair: ConnectorCredentialPair, beat: _Beat
) -> None:
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.PASSED)])
    row = get_capability_report_row(
        db_session, slack_pair.credential_id, slack_pair.connector_id
    )
    assert row is not None
    row.report = {"unexpected": "shape"}
    db_session.commit()

    beat.run()
    beat.assert_waiting()
    assert (
        _hold_reason(db_session, slack_pair) == IndexingHoldReason.CHECKS_FAILED_TO_RUN
    )


@pytest.fixture
def basic_user(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "first_hold_viewer")
    yield user
    delete_test_user(db_session, user)
    db_session.commit()


def test_a_read_only_viewer_sees_the_hold_without_the_failed_checks(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    beat: _Beat,
    admin: User,
    basic_user: User,
) -> None:
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])
    beat.run()
    waiting = beat.assert_waiting()

    # The pair is public, so a basic user reads it but cannot operate it.
    admin_hold = get_cc_pair_full_info(
        slack_pair.id, user=admin, db_session=db_session
    ).indexing_hold
    assert admin_hold is not None
    assert admin_hold.reason == IndexingHoldReason.REQUIRED_CHECKS_FAILED
    assert admin_hold.index_attempt_id == waiting.id
    assert [check.check_id for check in admin_hold.failed_checks] == ["slack_token"]

    viewer_info = get_cc_pair_full_info(
        slack_pair.id, user=basic_user, db_session=db_session
    )
    assert viewer_info.is_editable_for_current_user is False
    viewer_hold = viewer_info.indexing_hold
    assert viewer_hold is not None
    assert viewer_hold.reason == IndexingHoldReason.REQUIRED_CHECKS_FAILED
    assert viewer_hold.index_attempt_id == waiting.id
    assert viewer_hold.failed_checks == []


def test_nothing_waits_with_connector_checks_off(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    beat: _Beat,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(indexing_hold, "CONNECTOR_CHECKS_ENABLED", False)
    _complete(db_session, slack_pair, [_result(CapabilityCheckStatus.FAILED)])

    beat.run()
    beat.assert_started()
    assert (
        get_cc_pair_full_info(
            slack_pair.id, user=admin, db_session=db_session
        ).indexing_hold
        is None
    )


@pytest.mark.parametrize(
    "settings_status, indexes",
    [(IndexModelStatus.FUTURE, True), (IndexModelStatus.PRESENT, False)],
)
def test_a_paused_pair_indexes_only_into_a_future_index(
    db_session: Session,
    slack_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    settings_status: IndexModelStatus,
    indexes: bool,
) -> None:
    """A model switch reindexes paused pairs too, so creation skips a PAUSED
    pair only for the live index."""
    slack_pair.status = ConnectorCredentialPairStatus.PAUSED
    db_session.commit()
    target = (
        make_future_search_settings(db_session)
        if settings_status == IndexModelStatus.FUTURE
        else search_settings
    )
    beat = _Beat(db_session, slack_pair, target)
    try:
        attempt_id = try_creating_docfetching_task(
            beat.celery_app,
            slack_pair,
            target,
            False,
            db_session,
            get_redis_client(),
            get_current_tenant_id(),
        )
        if indexes:
            assert attempt_id is not None
            assert beat.assert_started().id == attempt_id
        else:
            assert attempt_id is None
            assert beat.attempts() == []
            assert beat.sent_attempt_ids() == []
    finally:
        if target is not search_settings:
            db_session.rollback()
            db_session.execute(
                delete(IndexAttempt).where(IndexAttempt.search_settings_id == target.id)
            )
            db_session.execute(
                delete(SearchSettings).where(SearchSettings.id == target.id)
            )
            db_session.commit()
