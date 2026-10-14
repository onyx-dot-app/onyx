"""
Revoking a user's sessions after a password reset or change. Real Redis +
Postgres; the strategy and UserManager are called directly.
"""

import secrets
from collections.abc import Generator
from typing import cast

import pytest
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import AuthBackend
from onyx.auth.session_tokens import SessionRejectionReason, get_session_rejection
from onyx.auth.users import TenantAwareRedisStrategy, UserManager
from onyx.configs.app_configs import (
    REDIS_AUTH_KEY_PREFIX,
    REDIS_USER_SESSIONS_KEY_PREFIX,
)
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import AccessToken, OAuthAccount, User
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_raw_redis_client
from tests.external_dependency_unit.conftest import create_test_user

_OLD_PASSWORD = "Old-Passw0rd-For-Tests!"
_NEW_PASSWORD = "New-Passw0rd-For-Tests!"


@pytest.fixture
def written_tokens() -> Generator[list[str], None, None]:
    tokens: list[str] = []
    yield tokens
    redis = get_raw_redis_client()
    for token in tokens:
        redis.delete(REDIS_AUTH_KEY_PREFIX + token)


def _cleanup_index(user: User) -> None:
    get_raw_redis_client().delete(f"{REDIS_USER_SESSIONS_KEY_PREFIX}{user.id}")


def _indexed_tokens(user: User) -> set[str]:
    members = cast(
        set[bytes],
        get_raw_redis_client().smembers(f"{REDIS_USER_SESSIONS_KEY_PREFIX}{user.id}"),
    )
    return {m.decode() for m in members}


async def _read_user_id(token: str) -> str | None:
    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        user = await TenantAwareRedisStrategy().read_token(token, UserManager(user_db))
        return str(user.id) if user else None


def _set_password(db_session: Session, user: User, password: str) -> None:
    user.hashed_password = PasswordHelper().hash(password)
    db_session.commit()


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_redis_revoke_keeps_only_the_kept_session(
    db_session: Session, written_tokens: list[str]
) -> None:
    user = create_test_user(db_session, "revoke_keep")
    other_user = create_test_user(db_session, "revoke_bystander")
    strategy = TenantAwareRedisStrategy()
    try:
        kept, revoked_a, revoked_b, bystander = (
            await strategy.write_token(user),
            await strategy.write_token(user),
            await strategy.write_token(user),
            await strategy.write_token(other_user),
        )
        written_tokens.extend([kept, revoked_a, revoked_b, bystander])
        assert _indexed_tokens(user) == {kept, revoked_a, revoked_b}

        await strategy.revoke_user_sessions(str(user.id), keep_token=kept)

        assert await _read_user_id(kept) == str(user.id)
        assert await _read_user_id(bystander) == str(other_user.id)
        for token in (revoked_a, revoked_b):
            assert await _read_user_id(token) is None
            rejection = get_session_rejection()
            assert rejection is not None
            assert rejection.reason == SessionRejectionReason.TERMINATED
        assert _indexed_tokens(user) == {kept}
    finally:
        _cleanup_index(user)
        _cleanup_index(other_user)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_redis_logout_and_refresh_maintain_index(
    db_session: Session, written_tokens: list[str]
) -> None:
    user = create_test_user(db_session, "revoke_index")
    strategy = TenantAwareRedisStrategy()
    try:
        logged_out = await strategy.write_token(user)
        refreshed = await strategy.write_token(user)
        written_tokens.extend([logged_out, refreshed])

        await strategy.destroy_token(logged_out, user)
        # A session written before the index existed joins it on refresh.
        get_raw_redis_client().srem(
            f"{REDIS_USER_SESSIONS_KEY_PREFIX}{user.id}", refreshed
        )
        assert await strategy.refresh_token(refreshed, user) == refreshed

        assert _indexed_tokens(user) == {refreshed}
    finally:
        _cleanup_index(user)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_admin_reset_revokes_every_redis_session(
    db_session: Session, written_tokens: list[str]
) -> None:
    user = create_test_user(db_session, "revoke_admin_reset")
    strategy = TenantAwareRedisStrategy()
    try:
        web_token = await strategy.write_token(user)
        mobile_token = await strategy.write_token(user)
        written_tokens.extend([web_token, mobile_token])

        async with get_async_session_context_manager() as async_session:
            user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
            await UserManager(user_db).reset_password_as_admin(user.id)

        assert await _read_user_id(web_token) is None
        assert await _read_user_id(mobile_token) is None
        assert _indexed_tokens(user) == set()
    finally:
        _cleanup_index(user)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_change_password_keeps_current_redis_session(
    db_session: Session, written_tokens: list[str]
) -> None:
    user = create_test_user(db_session, "revoke_change_redis")
    _set_password(db_session, user, _OLD_PASSWORD)
    strategy = TenantAwareRedisStrategy()
    try:
        current = await strategy.write_token(user)
        other = await strategy.write_token(user)
        written_tokens.extend([current, other])

        async with get_async_session_context_manager() as async_session:
            user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
            manager = UserManager(user_db)
            db_user = await manager.get(user.id)
            await manager.change_password_if_old_matches(
                db_user, _OLD_PASSWORD, _NEW_PASSWORD, keep_token=current
            )

        assert await _read_user_id(current) == str(user.id)
        assert await _read_user_id(other) is None
    finally:
        _cleanup_index(user)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_change_password_wrong_old_password_revokes_nothing(
    db_session: Session, written_tokens: list[str]
) -> None:
    user = create_test_user(db_session, "revoke_wrong_old")
    _set_password(db_session, user, _OLD_PASSWORD)
    strategy = TenantAwareRedisStrategy()
    try:
        token = await strategy.write_token(user)
        written_tokens.append(token)

        async with get_async_session_context_manager() as async_session:
            user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
            manager = UserManager(user_db)
            db_user = await manager.get(user.id)
            with pytest.raises(OnyxError):
                await manager.change_password_if_old_matches(
                    db_user, "not-the-old-password", _NEW_PASSWORD
                )

        assert await _read_user_id(token) == str(user.id)
    finally:
        _cleanup_index(user)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_postgres_backend_deletes_other_access_tokens(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("onyx.auth.users.AUTH_BACKEND", AuthBackend.POSTGRES)
    user = create_test_user(db_session, "revoke_change_pg")
    other_user = create_test_user(db_session, "revoke_bystander_pg")
    _set_password(db_session, user, _OLD_PASSWORD)
    current, other, bystander = (secrets.token_urlsafe() for _ in range(3))
    db_session.add_all(
        [
            AccessToken(token=current, user_id=user.id),
            AccessToken(token=other, user_id=user.id),
            AccessToken(token=bystander, user_id=other_user.id),
        ]
    )
    db_session.commit()

    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        manager = UserManager(user_db)
        db_user = await manager.get(user.id)
        await manager.change_password_if_old_matches(
            db_user, _OLD_PASSWORD, _NEW_PASSWORD, keep_token=current
        )

    def _remaining() -> set[str]:
        db_session.expire_all()
        rows = db_session.scalars(
            select(AccessToken).where(
                AccessToken.user_id.in_([user.id, other_user.id])  # ty: ignore[unresolved-attribute]
            )
        )
        return {row.token for row in rows}

    assert _remaining() == {current, bystander}

    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        await UserManager(user_db).reset_password_as_admin(user.id)

    assert _remaining() == {bystander}
