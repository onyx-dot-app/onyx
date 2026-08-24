"""Single-tenant OIDC callback must persist `oidc_expiry` on the existing
OAuth user without blocking on another connection's row lock, and must not
leave a second transaction idle on `"user"`.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

import onyx.auth.users as users_module
from onyx.auth.users import UserManager
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import OAuthAccount, User
from onyx.server.security.store import _build_env_defaults
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

_CALLBACK_TIMEOUT_SECONDS = 5
_POLL_INTERVAL_SECONDS = 0.2
_OAUTH_NAME = "oidc"


def _idle_user_lock_pids(exclude: set[int]) -> list[int]:
    """Backends sitting idle while still holding a lock on `"user"`."""
    with get_session_with_current_tenant() as session:
        checker_pid = session.execute(text("SELECT pg_backend_pid()")).scalar()
        exclude = exclude | {int(checker_pid)}
        pids = session.execute(
            text(
                "SELECT DISTINCT a.pid "
                "FROM pg_stat_activity a "
                "JOIN pg_locks l ON l.pid = a.pid "
                "JOIN pg_class c ON c.oid = l.relation "
                "WHERE a.datname = current_database() "
                "AND a.state = 'idle in transaction' "
                "AND c.relname = 'user'"
            )
        ).scalars()
        return [int(pid) for pid in pids if int(pid) not in exclude]


def _assert_no_idle_user_lock(exclude: set[int]) -> None:
    deadline = time.monotonic() + 1.0
    leftover: list[int] = []
    while time.monotonic() < deadline:
        leftover = _idle_user_lock_pids(exclude)
        if not leftover:
            return
        time.sleep(0.05)
    pytest.fail(f'leftover idle-in-transaction lock on "user"; pids={leftover}')


def _attach_oauth_account(db_session: Session, user: User) -> str:
    account_id = f"entra-{uuid4().hex}"
    db_session.add(
        OAuthAccount(
            user_id=user.id,
            oauth_name=_OAUTH_NAME,
            account_id=account_id,
            account_email=user.email,
            access_token="test-access-token",
            refresh_token="",
        )
    )
    db_session.commit()
    return account_id


def _delete_oauth_accounts(db_session: Session, user: User) -> None:
    db_session.execute(
        delete(OAuthAccount).where(OAuthAccount.__table__.c.user_id == user.id)
    )


async def _run_oauth_callback(
    *,
    user_email: str,
    account_id: str,
    expires_at: int | None,
    track_external_idp_expiry: bool,
    monkeypatch: pytest.MonkeyPatch,
    exclude_pids: set[int],
) -> User:
    monkeypatch.setattr(users_module, "MULTI_TENANT", False)
    monkeypatch.setattr(
        users_module,
        "get_security_settings",
        lambda: _build_env_defaults().model_copy(
            update={"track_external_idp_expiry": track_external_idp_expiry}
        ),
    )

    async with get_async_session_context_manager() as injected_session:
        injected_pid = (
            await injected_session.execute(text("SELECT pg_backend_pid()"))
        ).scalar()
        assert injected_pid is not None
        watched_pids = exclude_pids | {int(injected_pid)}

        manager = UserManager(
            SQLAlchemyUserDatabase(injected_session, User, OAuthAccount)
        )
        task = asyncio.create_task(
            manager.oauth_callback(
                oauth_name=_OAUTH_NAME,
                access_token="rotated-access-token",
                account_id=account_id,
                account_email=user_email,
                expires_at=expires_at,
                is_verified_by_default=True,
            )
        )
        deadline = time.monotonic() + _CALLBACK_TIMEOUT_SECONDS
        idle_pids: list[int] = []
        while not task.done():
            if time.monotonic() >= deadline:
                idle_pids = _idle_user_lock_pids(watched_pids)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                pytest.fail(
                    "oauth_callback blocked instead of writing oidc_expiry; "
                    f"idle-in-transaction pids={idle_pids}"
                )
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            idle_pids = _idle_user_lock_pids(watched_pids)
        return task.result()


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_existing_oauth_login_writes_oidc_expiry(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_test_user(db_session, "oidc_expiry_write")
    account_id = _attach_oauth_account(db_session, user)
    expires_at = int(datetime.now(timezone.utc).timestamp()) + 3600

    sync_pid = db_session.execute(text("SELECT pg_backend_pid()")).scalar()
    try:
        result = await _run_oauth_callback(
            user_email=user.email,
            account_id=account_id,
            expires_at=expires_at,
            track_external_idp_expiry=True,
            monkeypatch=monkeypatch,
            exclude_pids={int(sync_pid)},
        )
        assert result.id == user.id

        db_session.expire_all()
        persisted = db_session.get(User, user.id)
        assert persisted is not None
        assert persisted.oidc_expiry is not None
        assert persisted.oidc_expiry == datetime.fromtimestamp(
            expires_at, tz=timezone.utc
        )
        sync_pid = db_session.execute(text("SELECT pg_backend_pid()")).scalar()
        _assert_no_idle_user_lock({int(sync_pid)})
    finally:
        _delete_oauth_accounts(db_session, user)
        delete_test_user(db_session, user)
        db_session.commit()


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_existing_oauth_login_clears_oidc_expiry_when_tracking_disabled(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = create_test_user(db_session, "oidc_expiry_clear")
    user.oidc_expiry = datetime.now(timezone.utc)
    db_session.commit()
    account_id = _attach_oauth_account(db_session, user)

    sync_pid = db_session.execute(text("SELECT pg_backend_pid()")).scalar()
    try:
        result = await _run_oauth_callback(
            user_email=user.email,
            account_id=account_id,
            expires_at=int(datetime.now(timezone.utc).timestamp()) + 3600,
            track_external_idp_expiry=False,
            monkeypatch=monkeypatch,
            exclude_pids={int(sync_pid)},
        )
        assert result.id == user.id
        assert result.oidc_expiry is None

        db_session.expire_all()
        persisted = db_session.get(User, user.id)
        assert persisted is not None
        assert persisted.oidc_expiry is None
        sync_pid = db_session.execute(text("SELECT pg_backend_pid()")).scalar()
        _assert_no_idle_user_lock({int(sync_pid)})
    finally:
        _delete_oauth_accounts(db_session, user)
        delete_test_user(db_session, user)
        db_session.commit()
