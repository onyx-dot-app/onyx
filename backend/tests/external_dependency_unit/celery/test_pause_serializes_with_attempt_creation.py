"""A pause and the creation of an index attempt take the pair's row lock, so
they run one after the other. A pause that starts while an attempt is being
created waits for it, then cancels it."""

import threading
import time
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docfetching import task_creation_utils
from onyx.background.celery.tasks.docfetching.task_creation_utils import (
    try_creating_docfetching_task,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.indexing_hold_models import IndexingHold
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair, IndexAttempt, User
from onyx.db.search_settings import get_current_search_settings
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents import cc_pair as cc_pair_api
from onyx.server.documents.cc_pair import update_cc_pair_status
from onyx.server.documents.models import CCStatusUpdateRequest
from onyx.utils.threadpool_concurrency import run_in_background, wait_on_background
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_WAIT_SECONDS = 15.0


@pytest.fixture
def active_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    cc_pair = make_cc_pair(db_session, source=DocumentSource.FILE)
    cc_pair.status = ConnectorCredentialPairStatus.ACTIVE
    db_session.commit()
    yield cc_pair
    db_session.rollback()
    db_session.execute(
        delete(IndexAttempt).where(
            IndexAttempt.connector_credential_pair_id == cc_pair.id
        )
    )
    db_session.commit()
    cleanup_cc_pair(db_session, cc_pair)


@pytest.fixture
def admin(db_session: Session) -> Generator[User, None, None]:
    user = create_test_user(db_session, "pause_row_lock_admin", is_admin=True)
    yield user
    delete_test_user(db_session, user)
    db_session.commit()


def _pause_is_blocked_or_done(db_session: Session, pause_done: threading.Event) -> bool:
    if pause_done.is_set():
        return True
    waiting_on_lock = db_session.scalar(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE wait_event_type = 'Lock' AND datname = current_database()"
        )
    )
    db_session.rollback()
    return bool(waiting_on_lock)


def test_a_pause_during_attempt_creation_cancels_the_new_attempt(
    db_session: Session,
    active_pair: ConnectorCredentialPair,
    admin: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The status endpoint sends CHECK_FOR_INDEXING and revokes tasks; record
    # those calls instead of reaching the shared broker.
    api_celery = MagicMock()
    monkeypatch.setattr(cc_pair_api, "client_app", api_celery)

    status_checked = threading.Event()
    release_creator = threading.Event()
    pause_done = threading.Event()

    # The hold check runs after the status check and before the insert. Stop
    # the creator there.
    def hold_after_status_check(
        _db_session: Session, _cc_pair: ConnectorCredentialPair
    ) -> IndexingHold | None:
        status_checked.set()
        release_creator.wait(_WAIT_SECONDS)
        return None

    monkeypatch.setattr(
        task_creation_utils, "get_first_indexing_hold", hold_after_status_check
    )

    tenant_id = get_current_tenant_id()
    creator_celery = MagicMock()

    def create() -> int | None:
        with get_session_with_current_tenant() as session:
            cc_pair = get_connector_credential_pair_from_id(session, active_pair.id)
            if cc_pair is None:
                raise RuntimeError("test pair is missing")
            return try_creating_docfetching_task(
                celery_app=creator_celery,
                cc_pair=cc_pair,
                search_settings=get_current_search_settings(session),
                reindex=False,
                db_session=session,
                r=get_redis_client(tenant_id=tenant_id),
                tenant_id=tenant_id,
            )

    def pause() -> None:
        with get_session_with_current_tenant() as session:
            user = session.get(User, admin.id)
            if user is None:
                raise RuntimeError("test admin is missing")
            update_cc_pair_status(
                active_pair.id,
                CCStatusUpdateRequest(status=ConnectorCredentialPairStatus.PAUSED),
                user=user,
                db_session=session,
            )
        pause_done.set()

    creator = run_in_background(create)
    try:
        assert status_checked.wait(_WAIT_SECONDS)
        pauser = run_in_background(pause)
        try:
            # Before the fix the pause commits here without the new attempt.
            # With the fix it waits on the creator's row lock.
            deadline = time.monotonic() + _WAIT_SECONDS
            while not _pause_is_blocked_or_done(db_session, pause_done):
                assert time.monotonic() < deadline, "the pause never started"
                time.sleep(0.05)
        finally:
            release_creator.set()
            wait_on_background(pauser)
    finally:
        release_creator.set()
        attempt_id = wait_on_background(creator)

    assert attempt_id is not None
    db_session.expire_all()
    attempt = db_session.scalar(
        select(IndexAttempt).where(IndexAttempt.id == attempt_id)
    )
    assert attempt is not None
    assert attempt.cancellation_requested
    api_celery.control.revoke.assert_called_once_with(attempt.celery_task_id)
    pair = get_connector_credential_pair_from_id(db_session, active_pair.id)
    assert pair is not None
    assert pair.status == ConnectorCredentialPairStatus.PAUSED
