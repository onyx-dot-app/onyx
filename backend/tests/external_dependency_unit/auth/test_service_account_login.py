"""A service account authenticates only with its API key: no password login, no
password reset mail, and no access once the account is deactivated."""

from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.password import PasswordHelper
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import onyx.auth.users as users_module
from onyx.auth.api_key import ApiKeyDescriptor, hash_api_key
from onyx.db.api_key import insert_api_key
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.enums import AccountType
from onyx.db.models import ApiKey, User
from onyx.server.api_key.models import APIKeyArgs
from onyx.server.security.store import _build_env_defaults
from onyx.server.utils import BasicAuthenticationError

_PASSWORD = "Correct-Horse-Battery-9!"


@pytest.fixture
def service_account(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[User, str], None, None]:
    descriptor: ApiKeyDescriptor = insert_api_key(
        db_session=db_session,
        api_key_args=APIKeyArgs(name=f"sa_login_{uuid4().hex[:8]}"),
        user_id=None,
    )
    raw_key: str | None = descriptor.api_key
    assert raw_key is not None
    row: ApiKey | None = db_session.scalar(
        select(ApiKey).where(ApiKey.hashed_api_key == hash_api_key(raw_key))
    )
    assert row is not None
    user: User = row.user
    assert user.account_type == AccountType.SERVICE_ACCOUNT
    # Simulate a completed reset: the account now has a password the caller knows.
    user.hashed_password = PasswordHelper().hash(_PASSWORD)
    db_session.commit()
    yield user, raw_key
    db_session.delete(row)
    db_session.delete(user)
    db_session.commit()


def _manager(async_session: AsyncSession) -> users_module.UserManager:
    return users_module.UserManager(SQLAlchemyUserDatabase(async_session, User))


@pytest.mark.asyncio
async def test_forgot_password_sends_no_mail_for_service_account(
    service_account: tuple[User, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = service_account
    send_mail: MagicMock = MagicMock()
    monkeypatch.setattr(users_module, "EMAIL_CONFIGURED", True)
    monkeypatch.setattr(users_module, "send_forgot_password_email", send_mail)

    async with get_async_session_context_manager() as async_session:
        await _manager(async_session).on_after_forgot_password(user, "reset-token")

    send_mail.assert_not_called()


@pytest.mark.asyncio
async def test_password_login_refused_for_service_account(
    service_account: tuple[User, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = service_account
    # Pin password auth on so only the account-type check can refuse the login.
    settings = _build_env_defaults().model_copy(update={"password_auth_enabled": True})
    monkeypatch.setattr(users_module, "get_security_settings", lambda: settings)
    credentials: OAuth2PasswordRequestForm = OAuth2PasswordRequestForm(
        username=user.email, password=_PASSWORD
    )

    async with get_async_session_context_manager() as async_session:
        with pytest.raises(BasicAuthenticationError) as exc_info:
            await _manager(async_session).authenticate(credentials)

    assert exc_info.value.detail == "NO_WEB_LOGIN_AND_HAS_NO_PASSWORD"


async def _resolve_with_key(raw_key: str) -> User | None:
    request: Request = Request(
        scope={
            "type": "http",
            "headers": [(b"authorization", f"Bearer {raw_key}".encode())],
        }
    )
    async with get_async_session_context_manager() as async_session:
        return await users_module._resolve_optional_user(
            request, async_session, None, _manager(async_session)
        )


@pytest.mark.asyncio
async def test_key_of_deactivated_service_account_is_rejected(
    db_session: Session,
    service_account: tuple[User, str],
) -> None:
    user, raw_key = service_account

    resolved: User | None = await _resolve_with_key(raw_key)
    assert resolved is not None
    assert resolved.id == user.id

    user.is_active = False
    db_session.commit()

    assert await _resolve_with_key(raw_key) is None
