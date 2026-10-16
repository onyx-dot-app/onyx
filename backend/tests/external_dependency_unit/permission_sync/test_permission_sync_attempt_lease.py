"""
Lease coverage for doc permission and external group sync attempts: renewal,
the expired-lease reaper, and the terminal writes of a worker that lost its
attempt.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ee.onyx.db.external_perm import (
    ExternalUserGroup,
    mark_old_external_groups_as_stale,
    remove_stale_external_groups,
    upsert_external_groups,
)
from onyx.background.celery.tasks.shared.lease_heartbeat import LeaseHeartbeat
from onyx.configs.constants import DocumentSource
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import PermissionSyncStatus
from onyx.db.models import (
    DocPermissionSyncAttempt,
    ExternalGroupPermissionSyncAttempt,
    User__ExternalUserGroupId,
)
from onyx.db.permission_sync_attempt import (
    DocPermissionSyncProgress,
    PermissionSyncAttemptLostError,
    complete_doc_permission_sync_attempt,
    complete_external_group_sync_attempt,
    create_doc_permission_sync_attempt,
    create_external_group_sync_attempt,
    fail_expired_doc_permission_sync_attempts,
    fail_expired_external_group_sync_attempts,
    mark_doc_permission_sync_attempt_failed,
    mark_doc_permission_sync_attempt_in_progress,
    mark_external_group_sync_attempt_failed,
    mark_external_group_sync_attempt_in_progress,
    renew_doc_permission_sync_attempt_lease,
    renew_external_group_sync_attempt_lease,
)
from tests.external_dependency_unit.permission_sync.conftest import (
    create_test_connector_credential_pair,
)

_LEASE = timedelta(minutes=15)


@dataclass(frozen=True)
class _AttemptKind:
    model: type[DocPermissionSyncAttempt] | type[ExternalGroupPermissionSyncAttempt]
    create: Callable[[int, Session], int]
    start: Callable[[int, Session], object]
    renew: Callable[[int, Session], bool]
    reap: Callable[[Session, timedelta, timedelta], list[int]]
    fail: Callable[[int, Session, str], None]
    complete: Callable[[Session, int], object]


_DOC = _AttemptKind(
    model=DocPermissionSyncAttempt,
    create=create_doc_permission_sync_attempt,
    start=mark_doc_permission_sync_attempt_in_progress,
    renew=renew_doc_permission_sync_attempt_lease,
    reap=fail_expired_doc_permission_sync_attempts,
    fail=lambda attempt_id, db_session, msg: mark_doc_permission_sync_attempt_failed(
        attempt_id, db_session, error_message=msg
    ),
    complete=lambda db_session, attempt_id: complete_doc_permission_sync_attempt(
        db_session, attempt_id, total_docs_synced=1, docs_with_permission_errors=0
    ),
)
_GROUP = _AttemptKind(
    model=ExternalGroupPermissionSyncAttempt,
    create=create_external_group_sync_attempt,
    start=mark_external_group_sync_attempt_in_progress,
    renew=renew_external_group_sync_attempt_lease,
    reap=fail_expired_external_group_sync_attempts,
    fail=lambda attempt_id, db_session, msg: mark_external_group_sync_attempt_failed(
        attempt_id, db_session, error_message=msg
    ),
    complete=lambda db_session, attempt_id: complete_external_group_sync_attempt(
        db_session,
        attempt_id,
        total_users_processed=1,
        total_groups_processed=1,
        total_group_memberships_synced=1,
    ),
)


@pytest.fixture(params=[_DOC, _GROUP], ids=["doc", "group"])
def kind(request: pytest.FixtureRequest) -> _AttemptKind:
    return request.param


def _started_attempt(kind: _AttemptKind, db_session: Session) -> int:
    cc_pair = create_test_connector_credential_pair(db_session)
    attempt_id = kind.create(cc_pair.id, db_session)
    kind.start(attempt_id, db_session)
    return attempt_id


def _set_times(
    kind: _AttemptKind,
    db_session: Session,
    attempt_id: int,
    **times: datetime | None,
) -> None:
    db_session.execute(
        update(kind.model).where(kind.model.id == attempt_id).values(**times)
    )
    db_session.commit()


def _status(
    kind: _AttemptKind, db_session: Session, attempt_id: int
) -> PermissionSyncStatus:
    db_session.expire_all()
    attempt = db_session.get(kind.model, attempt_id)
    assert attempt is not None
    return attempt.status


def test_renew_succeeds_only_while_in_progress(
    kind: _AttemptKind, db_session: Session
) -> None:
    attempt_id = _started_attempt(kind, db_session)
    assert kind.renew(attempt_id, db_session)

    kind.fail(attempt_id, db_session, "boom")
    assert not kind.renew(attempt_id, db_session)


def test_reaper_fails_only_expired_attempts(
    kind: _AttemptKind, db_session: Session
) -> None:
    long_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    fresh = _started_attempt(kind, db_session)

    expired = _started_attempt(kind, db_session)
    _set_times(kind, db_session, expired, heartbeat_at=long_ago)

    # Started before leases existed: no heartbeat, old start time.
    legacy = _started_attempt(kind, db_session)
    _set_times(kind, db_session, legacy, heartbeat_at=None, time_started=long_ago)

    cc_pair = create_test_connector_credential_pair(db_session)
    never_started = kind.create(cc_pair.id, db_session)
    _set_times(kind, db_session, never_started, time_created=long_ago)

    failed_ids = kind.reap(db_session, _LEASE, _LEASE)

    assert {expired, legacy, never_started} <= set(failed_ids)
    assert fresh not in failed_ids
    assert _status(kind, db_session, fresh) == PermissionSyncStatus.IN_PROGRESS
    for attempt_id in (expired, legacy, never_started):
        assert _status(kind, db_session, attempt_id) == PermissionSyncStatus.FAILED


def test_worker_cannot_overwrite_reaped_attempt(
    kind: _AttemptKind, db_session: Session
) -> None:
    attempt_id = _started_attempt(kind, db_session)
    _set_times(
        kind,
        db_session,
        attempt_id,
        heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert attempt_id in kind.reap(db_session, _LEASE, _LEASE)

    with pytest.raises(PermissionSyncAttemptLostError):
        kind.complete(db_session, attempt_id)

    # The worker's own failure path keeps the reaper's reason.
    kind.fail(attempt_id, db_session, "worker error")
    db_session.expire_all()
    attempt = db_session.get(kind.model, attempt_id)
    assert attempt is not None
    assert attempt.status == PermissionSyncStatus.FAILED
    assert attempt.error_message is not None
    assert "lease" in attempt.error_message


def test_heartbeat_sets_lost_when_attempt_is_reaped(
    kind: _AttemptKind,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    attempt_id = _started_attempt(kind, db_session)

    def renew() -> bool:
        # Runs on the heartbeat thread, so it needs its own session.
        with get_session_with_current_tenant() as thread_session:
            return kind.renew(attempt_id, thread_session)

    with LeaseHeartbeat(
        "test", renew=renew, interval=0.05, max_silence=60, max_duration=60
    ) as heartbeat:
        time.sleep(0.2)
        assert not heartbeat.lost.is_set()

        kind.fail(attempt_id, db_session, "reaped")
        assert heartbeat.lost.wait(timeout=2)


def test_heartbeat_expires_when_renewals_keep_failing() -> None:
    """A worker that cannot reach the DB stops before the reaper can fail its
    attempt and let a replacement start."""

    def renew() -> bool:
        raise ConnectionError("db unreachable")

    with LeaseHeartbeat(
        "test", renew=renew, interval=0.05, max_silence=0.3, max_duration=60
    ) as heartbeat:
        assert not heartbeat.is_lost()
        time.sleep(0.5)
        assert heartbeat.is_lost()


def test_group_writes_are_refused_after_the_attempt_is_lost(
    db_session: Session,
) -> None:
    cc_pair = create_test_connector_credential_pair(db_session)
    attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
    mark_external_group_sync_attempt_in_progress(attempt_id, db_session)
    group = ExternalUserGroup(id="group-a", user_emails=["lease-user@example.com"])

    upsert_external_groups(
        db_session, cc_pair.id, [group], DocumentSource.GOOGLE_DRIVE, attempt_id
    )
    mark_old_external_groups_as_stale(db_session, cc_pair.id)

    mark_external_group_sync_attempt_failed(attempt_id, db_session, "reaped")

    with pytest.raises(PermissionSyncAttemptLostError):
        upsert_external_groups(
            db_session, cc_pair.id, [group], DocumentSource.GOOGLE_DRIVE, attempt_id
        )
    db_session.rollback()
    with pytest.raises(PermissionSyncAttemptLostError):
        remove_stale_external_groups(
            db_session, cc_pair.id, owning_attempt_id=attempt_id
        )
    db_session.rollback()

    # The stale rows a replacement sync would refresh are still there
    remaining = db_session.scalars(
        select(User__ExternalUserGroupId).where(
            User__ExternalUserGroupId.cc_pair_id == cc_pair.id
        )
    ).all()
    assert len(remaining) == 1
    assert remaining[0].stale


def test_heartbeat_stops_renewing_after_its_maximum_duration() -> None:
    """A hung job must not hold its lease for as long as the process lives."""
    renewals: list[float] = []

    def renew() -> bool:
        renewals.append(time.monotonic())
        return True

    with LeaseHeartbeat(
        "test", renew=renew, interval=0.05, max_silence=60, max_duration=0.3
    ) as heartbeat:
        assert heartbeat.lost.wait(timeout=2)
        count = len(renewals)
        time.sleep(0.2)
        assert len(renewals) == count


def test_renewal_writes_progress_and_completion_replaces_it(
    db_session: Session,
) -> None:
    attempt_id = _started_attempt(_DOC, db_session)
    progressed_at = datetime.now(timezone.utc)

    assert renew_doc_permission_sync_attempt_lease(
        attempt_id,
        db_session,
        DocPermissionSyncProgress(
            total_docs_synced=40,
            docs_with_permission_errors=2,
            last_progress_at=progressed_at,
        ),
    )
    db_session.expire_all()
    attempt = db_session.get(DocPermissionSyncAttempt, attempt_id)
    assert attempt is not None
    assert attempt.total_docs_synced == 40
    assert attempt.docs_with_permission_errors == 2
    assert attempt.last_progress_at == progressed_at

    completed = complete_doc_permission_sync_attempt(
        db_session, attempt_id, total_docs_synced=50, docs_with_permission_errors=3
    )
    assert completed.total_docs_synced == 50
    assert completed.docs_with_permission_errors == 3
