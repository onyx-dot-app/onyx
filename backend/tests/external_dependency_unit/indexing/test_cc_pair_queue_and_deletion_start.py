"""The connector page's pair info carries the queue place the status page shows,
and the start of a deletion once its fence is up."""

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    IndexingStatus,
    TaskStatus,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    IndexAttempt,
    User,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_delete import RedisConnectorDeletePayload
from onyx.server.documents import cc_pair as cc_pair_routes
from onyx.server.documents.cc_pair import get_cc_pair_full_info
from onyx.server.documents.index_monitoring import get_indexing_connectors
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair


@dataclass
class _Created:
    pairs: list[ConnectorCredentialPair] = field(default_factory=list)
    users: list[User] = field(default_factory=list)


@pytest.fixture
def created(db_session: Session) -> Generator[_Created, None, None]:
    """The pairs and users a test makes, removed with the pairs' attempts after
    it, so no queued attempt shifts a later test's queue place."""
    made = _Created()
    yield made
    db_session.rollback()
    db_session.query(IndexAttempt).filter(
        IndexAttempt.connector_credential_pair_id.in_([pair.id for pair in made.pairs])
    ).delete(synchronize_session=False)
    db_session.commit()
    for pair in made.pairs:
        cleanup_cc_pair(db_session, pair)
    delete_test_user(db_session, *made.users)
    db_session.commit()


def _create_user(
    db_session: Session, created: _Created, email_prefix: str, is_admin: bool = False
) -> User:
    user = create_test_user(db_session, email_prefix, is_admin=is_admin)
    created.users.append(user)
    return user


def _create_admin(db_session: Session, created: _Created) -> User:
    return _create_user(db_session, created, "queue_deletion_admin", is_admin=True)


def _create_cc_pair(
    db_session: Session,
    created: _Created,
    name: str,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
) -> ConnectorCredentialPair:
    owner: User = _create_user(db_session, created, "queue_deletion_owner")
    connector = Connector(
        name=f"{name} Connector",
        source=DocumentSource.GOOGLE_DRIVE,
        input_type=InputType.POLL,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
    )
    db_session.add(connector)
    db_session.flush()
    credential = Credential(credential_json={}, user_id=owner.id, admin_public=True)
    db_session.add(credential)
    db_session.flush()
    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=name,
        status=status,
        access_type=AccessType.PUBLIC,
        creator_id=owner.id,
    )
    db_session.add(cc_pair)
    db_session.commit()
    created.pairs.append(cc_pair)
    return cc_pair


def _queue_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    created: datetime,
    is_backfill: bool = False,
) -> None:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        is_backfill=is_backfill,
        status=IndexingStatus.NOT_STARTED,
        # A queued attempt joins the line only once its task is sent.
        celery_task_id=f"task-{uuid4().hex}",
    )
    db_session.add(attempt)
    db_session.flush()
    attempt.time_created = created
    db_session.commit()


def test_pair_info_queue_position_matches_the_fleet_row(
    db_session: Session, created: _Created
) -> None:
    prefix: str = f"Queue Place {uuid4().hex[:8]}"
    first = _create_cc_pair(db_session, created, f"{prefix} first")
    second = _create_cc_pair(db_session, created, f"{prefix} second")
    now: datetime = datetime.now(timezone.utc)
    _queue_attempt(db_session, first, now)
    _queue_attempt(db_session, second, now + timedelta(seconds=1))
    admin: User = _create_admin(db_session, created)

    fleet = get_indexing_connectors(
        page_num=0,
        page_size=20,
        q=prefix,
        status=None,
        user=admin,
        db_session=db_session,
    )
    fleet_positions: dict[int, int | None] = {
        row.cc_pair_id: row.queue_position for row in fleet.items
    }
    first_info = get_cc_pair_full_info(first.id, user=admin, db_session=db_session)
    second_info = get_cc_pair_full_info(second.id, user=admin, db_session=db_session)

    assert first_info.queue_position is not None
    # Other suites may leave attempts queued ahead, so the two are adjacent rather than 1 and 2.
    assert second_info.queue_position == first_info.queue_position + 1
    assert first_info.queue_position == fleet_positions[first.id]
    assert second_info.queue_position == fleet_positions[second.id]


def test_fenced_deletion_reports_its_start(
    db_session: Session, created: _Created
) -> None:
    cc_pair = _create_cc_pair(
        db_session,
        created,
        f"Deletion Start {uuid4().hex[:8]}",
        ConnectorCredentialPairStatus.DELETING,
    )
    admin: User = _create_admin(db_session, created)
    submitted: datetime = datetime.now(timezone.utc) - timedelta(minutes=5)
    redis_connector = RedisConnector(get_current_tenant_id(), cc_pair.id)
    redis_connector.delete.set_fence(
        RedisConnectorDeletePayload(num_docs_queued=3, submitted=submitted)
    )
    try:
        info = get_cc_pair_full_info(cc_pair.id, user=admin, db_session=db_session)
    finally:
        redis_connector.delete.set_fence(None)

    assert info.latest_deletion_attempt is not None
    assert info.latest_deletion_attempt.status == TaskStatus.STARTED
    assert info.latest_deletion_attempt.started_at == submitted


def test_pending_deletion_has_no_start(db_session: Session, created: _Created) -> None:
    cc_pair = _create_cc_pair(
        db_session,
        created,
        f"Deletion Pending {uuid4().hex[:8]}",
        ConnectorCredentialPairStatus.DELETING,
    )
    admin: User = _create_admin(db_session, created)

    info = get_cc_pair_full_info(cc_pair.id, user=admin, db_session=db_session)

    assert info.latest_deletion_attempt is not None
    assert info.latest_deletion_attempt.status == TaskStatus.PENDING
    assert info.latest_deletion_attempt.started_at is None


@pytest.mark.parametrize("fence_bytes", [b"not json", b"\xff\xfe"])
def test_unreadable_fence_reports_started_without_a_start(
    db_session: Session, created: _Created, fence_bytes: bytes
) -> None:
    cc_pair = _create_cc_pair(
        db_session,
        created,
        f"Deletion Unreadable {uuid4().hex[:8]}",
        ConnectorCredentialPairStatus.DELETING,
    )
    admin: User = _create_admin(db_session, created)
    redis_connector = RedisConnector(get_current_tenant_id(), cc_pair.id)
    redis_connector.delete.redis.set(redis_connector.delete.fence_key, fence_bytes)
    try:
        info = get_cc_pair_full_info(cc_pair.id, user=admin, db_session=db_session)
    finally:
        redis_connector.delete.set_fence(None)

    assert info.latest_deletion_attempt is not None
    assert info.latest_deletion_attempt.status == TaskStatus.STARTED
    assert info.latest_deletion_attempt.started_at is None


def test_pair_that_is_not_queued_skips_the_queue_scan(
    db_session: Session,
    created: _Created,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cc_pair = _create_cc_pair(db_session, created, f"Not Queued {uuid4().hex[:8]}")
    admin: User = _create_admin(db_session, created)

    def _no_scan(db_session: Session) -> dict[int, int]:  # noqa: ARG001
        raise AssertionError("the queue scan ran for a pair that is not queued")

    monkeypatch.setattr(cc_pair_routes, "get_queue_positions", _no_scan)

    info = get_cc_pair_full_info(cc_pair.id, user=admin, db_session=db_session)

    assert info.queue_position is None


def test_queued_backfill_after_a_finished_run_reports_its_place(
    db_session: Session, created: _Created
) -> None:
    """The latest normal run finished, and a backfill waits in the queue the
    card reads as Scheduled."""
    cc_pair = _create_cc_pair(db_session, created, f"Backfill {uuid4().hex[:8]}")
    finished = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.SUCCESS,
    )
    db_session.add(finished)
    db_session.commit()
    _queue_attempt(db_session, cc_pair, datetime.now(timezone.utc), is_backfill=True)
    admin: User = _create_admin(db_session, created)

    info = get_cc_pair_full_info(cc_pair.id, user=admin, db_session=db_session)

    assert info.queue_position is not None
