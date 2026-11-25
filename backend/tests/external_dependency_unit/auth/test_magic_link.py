"""The magic link against the real cache backend and the real database.

The token store keeps one record per token, burns it on the first read, and
gives it a bounded TTL. ``UserManager.magic_link_login`` creates, signs in, verifies or
promotes the user row for the address. Single-tenant, so the tenant is the
default schema.
"""

import hashlib
from collections.abc import Generator
from uuid import uuid4

import pytest
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.orm import Session

import onyx.auth.users as users_module
from onyx.auth.magic_link import (
    MagicLinkRecord,
    consume_magic_link,
    store_magic_link,
)
from onyx.auth.users import UserManager
from onyx.cache.factory import get_shared_cache_backend
from onyx.configs.app_configs import MAGIC_LINK_TOKEN_PREFIX, MAGIC_LINK_TTL_SECONDS
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import AccountType
from onyx.db.models import OAuthAccount, User
from onyx.db.users import get_user_by_email
from onyx.server.security.store import _build_env_defaults
from tests.external_dependency_unit.conftest import (
    MakeTestUser,
    delete_test_users_and_owned_rows,
)

RECORD = MagicLinkRecord(
    email="someone@example.com",
    start_new_team=True,
    next_url="/app",
    referral_source="ads",
)


def _cache_key(token: str) -> str:
    return (
        f"{MAGIC_LINK_TOKEN_PREFIX}{hashlib.sha256(token.encode('utf-8')).hexdigest()}"
    )


class TestTokenStore:
    @pytest.mark.asyncio
    async def test_a_record_comes_back_once(self) -> None:
        token = await store_magic_link(RECORD)

        assert await consume_magic_link(token) == RECORD
        assert await consume_magic_link(token) is None

    @pytest.mark.asyncio
    async def test_an_unknown_token_is_a_miss(self) -> None:
        assert await consume_magic_link(f"never-issued-{uuid4().hex}") is None

    @pytest.mark.asyncio
    async def test_the_cache_holds_the_hash_with_a_bounded_ttl(self) -> None:
        token = await store_magic_link(RECORD)
        cache = get_shared_cache_backend()
        try:
            assert not cache.exists(f"{MAGIC_LINK_TOKEN_PREFIX}{token}")
            assert 0 < cache.ttl(_cache_key(token)) <= MAGIC_LINK_TTL_SECONDS
        finally:
            await consume_magic_link(token)

    @pytest.mark.asyncio
    async def test_a_malformed_record_is_a_miss_and_is_burned(self) -> None:
        token = f"malformed-{uuid4().hex}"
        cache = get_shared_cache_backend()
        cache.set(_cache_key(token), b'{"start_new_team": "not a bool"}', 60)

        assert await consume_magic_link(token) is None
        assert not cache.exists(_cache_key(token))


@pytest.fixture
def single_tenant_open_sign_up(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default security settings and open sign-up, whatever the local
    workspace has set."""
    monkeypatch.setattr(users_module, "MULTI_TENANT", False)
    monkeypatch.setattr(users_module, "get_security_settings", _build_env_defaults)
    monkeypatch.setattr(users_module, "workspace_invite_only_enabled", lambda: False)


@pytest.fixture
def new_address(db_session: Session) -> Generator[str, None, None]:
    """An address with no user yet. Teardown deletes whatever the login made."""
    email = f"magic_link_new_{uuid4().hex[:8]}@example.com"
    yield email
    user = get_user_by_email(email, db_session)
    if user is not None:
        delete_test_users_and_owned_rows(db_session, [user.id], [email])


async def _magic_link_login(email: str) -> User:
    async with get_async_session_context_manager() as session:
        manager = UserManager(SQLAlchemyUserDatabase(session, User, OAuthAccount))
        return await manager.magic_link_login(email)


def _reload(db_session: Session, email: str) -> User:
    db_session.expire_all()
    user = get_user_by_email(email, db_session)
    if user is None:
        raise AssertionError(f"No user row for {email}")
    return user


@pytest.mark.usefixtures("tenant_context", "single_tenant_open_sign_up")
class TestMagicLinkLogin:
    @pytest.mark.asyncio
    async def test_a_new_address_gets_a_verified_standard_user(
        self, db_session: Session, new_address: str
    ) -> None:
        returned = await _magic_link_login(new_address)

        user = _reload(db_session, new_address)
        assert user.id == returned.id
        assert user.is_verified
        assert user.is_active
        assert user.account_type == AccountType.STANDARD
        assert user.hashed_password
        # on_after_register put the user in a default group.
        assert user.effective_permissions

    @pytest.mark.asyncio
    async def test_an_existing_user_signs_in_unchanged(
        self, db_session: Session, make_test_user: MakeTestUser
    ) -> None:
        existing = make_test_user("magic_link_existing")
        password_before = existing.hashed_password

        returned = await _magic_link_login(existing.email)

        user = _reload(db_session, existing.email)
        assert returned.id == existing.id
        assert user.hashed_password == password_before

    @pytest.mark.asyncio
    async def test_the_click_verifies_an_unverified_user(
        self, db_session: Session, make_test_user: MakeTestUser
    ) -> None:
        existing = make_test_user("magic_link_unverified")
        existing.is_verified = False
        db_session.commit()

        await _magic_link_login(existing.email)

        assert _reload(db_session, existing.email).is_verified

    @pytest.mark.asyncio
    async def test_a_permission_placeholder_becomes_the_account(
        self, db_session: Session, make_test_user: MakeTestUser
    ) -> None:
        placeholder = make_test_user(
            "magic_link_placeholder", account_type=AccountType.EXT_PERM_USER
        )

        returned = await _magic_link_login(placeholder.email)

        user = _reload(db_session, placeholder.email)
        assert returned.id == placeholder.id
        assert user.account_type == AccountType.STANDARD
        assert user.is_verified
