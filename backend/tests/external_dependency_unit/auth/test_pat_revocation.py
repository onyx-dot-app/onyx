"""
Revoking a user's personal access tokens after a password reset or change.
Real Postgres + Redis; UserManager is called directly.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi_users.jwt import generate_jwt
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.pat import hash_pat
from onyx.auth.users import UserManager
from onyx.configs.app_configs import REDIS_USER_SESSIONS_KEY_PREFIX
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import PatType
from onyx.db.models import OAuthAccount, PersonalAccessToken, User
from onyx.db.pat import (
    create_pat,
    resolve_pat,
    revoke_all_pats_for_user__no_commit,
    revoke_pat,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_raw_redis_client
from tests.external_dependency_unit.conftest import create_test_user

_OLD_PASSWORD = "Old-Passw0rd-For-Tests!"
_NEW_PASSWORD = "New-Passw0rd-For-Tests!"


@pytest.fixture
def users(db_session: Session) -> Generator[tuple[User, User], None, None]:
    user = create_test_user(db_session, "pat_reset_target")
    bystander = create_test_user(db_session, "pat_reset_bystander")
    user.hashed_password = PasswordHelper().hash(_OLD_PASSWORD)
    db_session.commit()
    yield user, bystander
    redis = get_raw_redis_client()
    for test_user in (user, bystander):
        redis.delete(f"{REDIS_USER_SESSIONS_KEY_PREFIX}{test_user.id}")


def _mint_pat(db_session: Session, user: User, pat_type: PatType) -> str:
    _, raw_token = create_pat(db_session, user.id, "test", None, pat_type=pat_type)
    db_session.commit()
    return raw_token


async def _pat_is_valid(raw_token: str) -> bool:
    async with get_async_session_context_manager() as async_session:
        return await resolve_pat(hash_pat(raw_token), async_session) is not None


def _revoked_flags(db_session: Session, user: User) -> list[bool]:
    db_session.expire_all()
    return [
        pat.is_revoked
        for pat in db_session.scalars(
            select(PersonalAccessToken).where(PersonalAccessToken.user_id == user.id)
        )
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_admin_reset_revokes_all_user_pats(
    db_session: Session, users: tuple[User, User]
) -> None:
    user, bystander = users
    user_token = _mint_pat(db_session, user, PatType.USER)
    craft_token = _mint_pat(db_session, user, PatType.CRAFT)
    bystander_token = _mint_pat(db_session, bystander, PatType.USER)
    assert await _pat_is_valid(user_token)

    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        await UserManager(user_db).reset_password_as_admin(user.id)

    assert not await _pat_is_valid(user_token)
    assert not await _pat_is_valid(craft_token)
    assert await _pat_is_valid(bystander_token)
    assert _revoked_flags(db_session, user) == [True, True]


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_change_password_revokes_pats(
    db_session: Session, users: tuple[User, User]
) -> None:
    user, _ = users
    token = _mint_pat(db_session, user, PatType.USER)

    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        manager = UserManager(user_db)
        db_user = await manager.get(user.id)
        await manager.change_password_if_old_matches(
            db_user, _OLD_PASSWORD, _NEW_PASSWORD
        )

    assert not await _pat_is_valid(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_forgot_password_reset_revokes_pats(
    db_session: Session, users: tuple[User, User]
) -> None:
    user, _ = users
    token = _mint_pat(db_session, user, PatType.USER)

    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        manager = UserManager(user_db)
        manager.reset_password_token_secret = "pat-revocation-test-secret"
        db_user = await manager.get(user.id)
        reset_token = generate_jwt(
            {
                "sub": str(db_user.id),
                "password_fgpt": manager.password_helper.hash(db_user.hashed_password),
                "aud": manager.reset_password_token_audience,
            },
            manager.reset_password_token_secret,
            manager.reset_password_token_lifetime_seconds,
        )
        await manager.reset_password(reset_token, _NEW_PASSWORD)

    assert not await _pat_is_valid(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_wrong_old_password_keeps_pats(
    db_session: Session, users: tuple[User, User]
) -> None:
    user, _ = users
    token = _mint_pat(db_session, user, PatType.USER)

    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        manager = UserManager(user_db)
        db_user = await manager.get(user.id)
        with pytest.raises(OnyxError):
            await manager.change_password_if_old_matches(
                db_user, "not-the-old-password", _NEW_PASSWORD
            )

    assert await _pat_is_valid(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_revoke_all_skips_already_revoked_pats(
    db_session: Session, users: tuple[User, User]
) -> None:
    user, _ = users
    old_pat, _ = create_pat(db_session, user.id, "old", None)
    revoke_pat(db_session, old_pat.id, user.id)
    _mint_pat(db_session, user, PatType.USER)

    async with get_async_session_context_manager() as async_session:
        assert await revoke_all_pats_for_user__no_commit(async_session, user.id) == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("tenant_context")
async def test_failed_pat_revocation_keeps_old_password(
    db_session: Session, users: tuple[User, User]
) -> None:
    """The new password and the PAT revocation commit together."""
    user, _ = users
    token = _mint_pat(db_session, user, PatType.USER)

    async with get_async_session_context_manager() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User, OAuthAccount)
        manager = UserManager(user_db)
        db_user = await manager.get(user.id)
        with (
            patch(
                "onyx.auth.users.revoke_all_pats_for_user__no_commit",
                side_effect=RuntimeError("revocation failed"),
            ),
            pytest.raises(RuntimeError),
        ):
            await manager.change_password_if_old_matches(
                db_user, _OLD_PASSWORD, _NEW_PASSWORD
            )

    db_session.expire_all()
    stored = db_session.get(User, user.id)
    assert stored is not None
    verified, _ = PasswordHelper().verify_and_update(
        _OLD_PASSWORD, stored.hashed_password
    )
    assert verified
    assert await _pat_is_valid(token)
