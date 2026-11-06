"""The beat backs off a pair whose permission syncs keep failing: after N
consecutive FAILED attempts it waits request_retry_delay(N) from the last one.
A CANCELED attempt neither counts nor ends the run of failures, a pair awaiting
its first permission sync counts only the attempts since its mark, and a manual
sync ignores the backoff."""

from collections.abc import Callable, Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing import tasks as perm_tasks
from onyx.configs.constants import DocumentSource
from onyx.db.connector_edit_requests import request_retry_delay
from onyx.db.enums import AccessType, PermissionSyncStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
)
from onyx.db.permission_sync_attempt import (
    complete_doc_permission_sync_attempt,
    delete_doc_permission_sync_attempts__no_commit,
    delete_external_group_permission_sync_attempts__no_commit,
    get_doc_permission_sync_retry_after,
    get_external_group_sync_retry_after,
    mark_doc_permission_sync_attempt_in_progress,
)
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_AttemptModel = (
    type[DocPermissionSyncAttempt] | type[ExternalGroupPermissionSyncAttempt]
)
_RetryAfterGetter = Callable[[int, Session], datetime | None]

_SYNC_KINDS = [
    pytest.param(
        DocPermissionSyncAttempt, get_doc_permission_sync_retry_after, id="doc"
    ),
    pytest.param(
        ExternalGroupPermissionSyncAttempt,
        get_external_group_sync_retry_after,
        id="group",
    ),
]

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def make_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[Callable[[], ConnectorCredentialPair], None, None]:
    pairs: list[ConnectorCredentialPair] = []

    def _make() -> ConnectorCredentialPair:
        # Confluence's doc sync does not wait for a first index, so a new
        # SYNC pair is due at once.
        pair = make_cc_pair(db_session, DocumentSource.CONFLUENCE)
        pair.access_type = AccessType.SYNC
        db_session.commit()
        pairs.append(pair)
        return pair

    try:
        yield _make
    finally:
        db_session.rollback()
        for pair in pairs:
            delete_doc_permission_sync_attempts__no_commit(db_session, pair.id)
            delete_external_group_permission_sync_attempts__no_commit(
                db_session, pair.id
            )
            db_session.commit()
            cleanup_cc_pair(db_session, pair)


def _add_finished_attempt(
    db_session: Session,
    model: _AttemptModel,
    cc_pair_id: int,
    status: PermissionSyncStatus,
    finished_at: datetime,
) -> None:
    started_at = finished_at - timedelta(seconds=10)
    db_session.add(
        model(
            connector_credential_pair_id=cc_pair_id,
            status=status,
            time_created=started_at,
            time_started=started_at,
            time_finished=finished_at,
        )
    )
    db_session.commit()


def _run_beat() -> list[int]:
    """Runs the doc permission sync beat and returns the pairs it dispatched."""
    dispatched: list[int] = []
    with (
        patch.object(perm_tasks, "fail_lost_queued_doc_permission_sync_attempts"),
        patch.object(
            perm_tasks,
            "try_creating_permissions_sync_task",
            side_effect=lambda _app, cc_pair_id, _tenant_id: dispatched.append(
                cc_pair_id
            ),
        ),
    ):
        result = perm_tasks.check_for_doc_permissions_sync.apply(
            kwargs={"tenant_id": TEST_TENANT_ID}
        ).get()
    # None means another beat held the lock, so nothing was checked.
    assert result is True
    return dispatched


def test_beat_backs_off_a_failing_pair_and_a_manual_sync_does_not(
    db_session: Session, make_pair: Callable[[], ConnectorCredentialPair]
) -> None:
    just_failed = make_pair()
    failed_earlier = make_pair()
    now = datetime.now(timezone.utc)
    # A minute back, so the manual sync below sorts after this failure even if
    # the database clock lags this process.
    _add_finished_attempt(
        db_session,
        DocPermissionSyncAttempt,
        just_failed.id,
        PermissionSyncStatus.FAILED,
        now - timedelta(minutes=1),
    )
    _add_finished_attempt(
        db_session,
        DocPermissionSyncAttempt,
        failed_earlier.id,
        PermissionSyncStatus.FAILED,
        now - request_retry_delay(1) - timedelta(minutes=1),
    )

    # Both pairs are due; only the one whose retry time has passed starts.
    dispatched = _run_beat()
    assert failed_earlier.id in dispatched
    assert just_failed.id not in dispatched

    # A manual sync starts during the backoff, and its success clears it.
    attempt_id = perm_tasks.try_creating_permissions_sync_task(
        MagicMock(), just_failed.id, TEST_TENANT_ID
    )
    assert attempt_id is not None
    mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)
    complete_doc_permission_sync_attempt(
        db_session, attempt_id, total_docs_synced=0, docs_with_permission_errors=0
    )
    assert get_doc_permission_sync_retry_after(just_failed.id, db_session) is None
    assert just_failed.id in _run_beat()


@pytest.mark.parametrize(("model", "get_retry_after"), _SYNC_KINDS)
def test_canceled_attempts_neither_count_nor_end_the_failures(
    db_session: Session,
    make_pair: Callable[[], ConnectorCredentialPair],
    model: _AttemptModel,
    get_retry_after: _RetryAfterGetter,
) -> None:
    pair = make_pair()
    statuses = [
        PermissionSyncStatus.FAILED,
        PermissionSyncStatus.CANCELED,
        PermissionSyncStatus.FAILED,
        # More cancels than the lookback holds; they must not push the
        # failures out of it.
        *[PermissionSyncStatus.CANCELED] * 10,
    ]
    for minute, status in enumerate(statuses):
        _add_finished_attempt(
            db_session, model, pair.id, status, _BASE + timedelta(minutes=minute)
        )

    last_failed_at = _BASE + timedelta(minutes=2)
    expected = last_failed_at + request_retry_delay(2)
    assert get_retry_after(pair.id, db_session) == expected


@pytest.mark.parametrize(("model", "get_retry_after"), _SYNC_KINDS)
def test_a_pending_pair_counts_only_attempts_since_its_mark(
    db_session: Session,
    make_pair: Callable[[], ConnectorCredentialPair],
    model: _AttemptModel,
    get_retry_after: _RetryAfterGetter,
) -> None:
    pair = make_pair()
    pending_since = _BASE + timedelta(minutes=10)
    _add_finished_attempt(
        db_session, model, pair.id, PermissionSyncStatus.FAILED, _BASE
    )
    # Started before the mark and failed after it.
    _add_finished_attempt(
        db_session,
        model,
        pair.id,
        PermissionSyncStatus.FAILED,
        pending_since + timedelta(seconds=5),
    )
    assert get_retry_after(pair.id, db_session) is not None

    pair.perm_sync_pending_since = pending_since
    db_session.commit()
    # The first sync after the access change is not delayed.
    assert get_retry_after(pair.id, db_session) is None

    # Failures after the mark back off as usual.
    last_failed_at = pending_since + timedelta(minutes=5)
    _add_finished_attempt(
        db_session, model, pair.id, PermissionSyncStatus.FAILED, last_failed_at
    )
    expected = last_failed_at + request_retry_delay(1)
    assert get_retry_after(pair.id, db_session) == expected
