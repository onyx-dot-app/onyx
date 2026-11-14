"""The chat retention task purges the Firecracker harness saves that
retention no longer keeps."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.ttl_management import tasks as ttl_tasks
from onyx.background.celery.tasks.build import tasks as build_tasks
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask
from onyx.db.chat import create_chat_session
from onyx.db.enums import BuildSessionStatus, SandboxStatus
from onyx.db.models import BuildSession, ChatSession, User
from onyx.db.users import delete_user_from_db
from onyx.server.features.build.sandbox.firecracker import purge as purge_module
from onyx.server.features.build.sandbox.firecracker.harness_state import (
    SAVED_SESSIONS_PREFIX,
    add_id,
    is_purged,
    mark_purged,
)
from onyx.server.features.build.sandbox.firecracker.session_saves import (
    session_save_lock,
)
from onyx.server.settings.models import Settings
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user

_TASKS = "ee.onyx.background.celery.tasks.ttl_management.tasks"
_RETENTION_DAYS = 30


def _build_session(db_session: Session, user: User, age_days: int) -> UUID:
    row = BuildSession(
        id=uuid4(),
        user_id=user.id,
        name="retention",
        status=BuildSessionStatus.ACTIVE,
        last_activity_at=datetime.now(tz=timezone.utc) - timedelta(days=age_days),
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _delete_user(db_session: Session, user_id: UUID) -> None:
    user = db_session.get(User, user_id)
    if user is not None:
        delete_user_from_db(user, db_session)


def _record_purges(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, UUID]]:
    """Records each purge and writes its purge mark, as the real purge does."""
    purged: list[tuple[UUID, UUID]] = []

    def purge(sandbox_id: UUID, session_id: UUID) -> None:
        purged.append((sandbox_id, session_id))
        mark_purged(get_cache_backend(), session_id=session_id)

    monkeypatch.setattr(purge_module, "purge_harness_session", purge)
    return purged


def _run_chain_end(tenant_id: str, chat_session_ids: list[UUID]) -> MagicMock:
    """Runs one retention batch that ends its chain. Returns `send_task`."""
    lease = MagicMock()
    lease.eval.return_value = 1
    task = ttl_tasks.perform_ttl_management_task
    with (
        patch(f"{_TASKS}.get_redis_client", return_value=lease),
        patch(
            f"{_TASKS}.load_settings",
            return_value=Settings(maximum_chat_retention_days=_RETENTION_DAYS),
        ),
        patch(
            f"{_TASKS}.get_chat_sessions_older_than",
            return_value=[(None, s) for s in chat_session_ids],
        ),
        patch.object(task.app, "send_task") as send_task,
    ):
        run_batch = task.run
        run_batch(_RETENTION_DAYS, "token", tenant_id=tenant_id)  # ty: ignore[invalid-argument-type]
    return send_task


def test_retention_purges_the_saves_it_no_longer_keeps(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    purged = _record_purges(monkeypatch)
    monkeypatch.setattr(purge_module, "HARNESS_PURGE_ENABLED", True)
    monkeypatch.setattr(ttl_tasks, "HARNESS_PURGE_ENABLED", True)
    tenant_id = get_current_tenant_id()
    tenant_cache = get_cache_backend(tenant_id=tenant_id)
    user = make_user(db_session, standard_account=True)
    user_id = user.id
    sandbox_id: UUID | None = None
    try:
        sandbox_id = make_sandbox(db_session, user, status=SandboxStatus.SLEEPING).id
        old_build = _build_session(db_session, user, age_days=_RETENTION_DAYS + 10)
        fresh_build = _build_session(db_session, user, age_days=1)
        expired_chat = create_chat_session(db_session, None, user.id, None).id
        kept_chat = create_chat_session(db_session, None, user.id, None).id
        orphan = uuid4()
        for session_id in (old_build, fresh_build, expired_chat, kept_chat, orphan):
            add_id(tenant_cache, SAVED_SESSIONS_PREFIX, sandbox_id, str(session_id))

        send_task = _run_chain_end(tenant_id, [expired_chat])

        db_session.expire_all()
        assert db_session.get(ChatSession, expired_chat) is None
        # The sweep runs on the sandbox queue, after the deletes commit.
        send_task.assert_called_once()
        assert send_task.call_args.args == (
            OnyxCeleryTask.PURGE_EXPIRED_HARNESS_SESSIONS,
        )
        assert send_task.call_args.kwargs["queue"] == OnyxCeleryQueues.SANDBOX
        assert send_task.call_args.kwargs["expires"] is not None
        sweep = build_tasks.purge_expired_harness_sessions_task.run
        with patch(
            "onyx.background.celery.tasks.build.tasks.load_settings",
            return_value=Settings(maximum_chat_retention_days=_RETENTION_DAYS),
        ):
            sweep(**send_task.call_args.kwargs["kwargs"])
        # Retention turned off while the sweep waited in the queue.
        with patch(
            "onyx.background.celery.tasks.build.tasks.load_settings",
            return_value=Settings(maximum_chat_retention_days=None),
        ):
            sweep(**send_task.call_args.kwargs["kwargs"])

        assert sorted(purged) == sorted(
            [(sandbox_id, old_build), (sandbox_id, expired_chat), (sandbox_id, orphan)]
        )
        # A build session opened again later can save new work.
        assert not is_purged(tenant_cache, sandbox_id, old_build)

        # A save in flight keeps the mark, so it cannot bring the files back.
        purged.clear()
        with session_save_lock(tenant_cache, old_build) as acquired:
            assert acquired
            purge_module.purge_expired_harness_sessions(
                _RETENTION_DAYS, limit=100, deadline=time.monotonic() + 60
            )
        assert (sandbox_id, old_build) in purged
        assert is_purged(tenant_cache, sandbox_id, old_build)

        purged.clear()
        purge_module.purge_expired_harness_sessions(
            _RETENTION_DAYS, limit=2, deadline=time.monotonic() + 60
        )
        assert len(purged) == 2

        purged.clear()
        purge_module.purge_expired_harness_sessions(
            _RETENTION_DAYS, limit=100, deadline=time.monotonic()
        )
        assert purged == []
    finally:
        db_session.rollback()
        if sandbox_id is not None:
            tenant_cache.delete(SAVED_SESSIONS_PREFIX + str(sandbox_id))
        _delete_user(db_session, user_id)


def test_retention_purges_nothing_when_firecracker_is_off(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    purged = _record_purges(monkeypatch)
    monkeypatch.setattr(purge_module, "HARNESS_PURGE_ENABLED", False)
    monkeypatch.setattr(ttl_tasks, "HARNESS_PURGE_ENABLED", False)
    tenant_id = get_current_tenant_id()
    tenant_cache = get_cache_backend(tenant_id=tenant_id)
    user = make_user(db_session, standard_account=True)
    user_id = user.id
    sandbox_id: UUID | None = None
    try:
        sandbox_id = make_sandbox(db_session, user, status=SandboxStatus.SLEEPING).id
        add_id(tenant_cache, SAVED_SESSIONS_PREFIX, sandbox_id, str(uuid4()))

        send_task = _run_chain_end(tenant_id, [])
        purge_module.purge_expired_harness_sessions(
            _RETENTION_DAYS, limit=100, deadline=time.monotonic() + 60
        )

        send_task.assert_not_called()
        assert purged == []
    finally:
        db_session.rollback()
        if sandbox_id is not None:
            tenant_cache.delete(SAVED_SESSIONS_PREFIX + str(sandbox_id))
        _delete_user(db_session, user_id)


def test_a_session_used_again_during_the_sweep_keeps_its_save(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(purge_module, "HARNESS_PURGE_ENABLED", True)
    tenant_cache = get_cache_backend(tenant_id=get_current_tenant_id())
    user = make_user(db_session, standard_account=True)
    user_id = user.id
    sandbox_id: UUID | None = None
    try:
        sandbox_id = make_sandbox(db_session, user, status=SandboxStatus.SLEEPING).id
        sessions = [
            _build_session(db_session, user, age_days=_RETENTION_DAYS + 10)
            for _ in range(2)
        ]
        for session_id in sessions:
            add_id(tenant_cache, SAVED_SESSIONS_PREFIX, sandbox_id, str(session_id))
        purged: list[UUID] = []

        def purge_and_resume_the_other(_sandbox_id: UUID, session_id: UUID) -> None:
            purged.append(session_id)
            db_session.execute(
                update(BuildSession)
                .where(BuildSession.id.in_(sessions), BuildSession.id != session_id)
                .values(last_activity_at=datetime.now(tz=timezone.utc))
            )
            db_session.commit()

        monkeypatch.setattr(
            purge_module, "purge_harness_session", purge_and_resume_the_other
        )

        purge_module.purge_expired_harness_sessions(
            _RETENTION_DAYS, limit=100, deadline=time.monotonic() + 60
        )

        assert len(purged) == 1
    finally:
        db_session.rollback()
        if sandbox_id is not None:
            tenant_cache.delete(SAVED_SESSIONS_PREFIX + str(sandbox_id))
        _delete_user(db_session, user_id)
