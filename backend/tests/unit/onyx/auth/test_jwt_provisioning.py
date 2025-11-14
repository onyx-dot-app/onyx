from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from onyx.auth import users as users_module


@pytest.mark.asyncio
async def test_get_or_create_user_updates_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing web-login users should be returned and their expiry synced."""
    monkeypatch.setattr(users_module, "TRACK_EXTERNAL_IDP_EXPIRY", True)
    invited_checked: dict[str, str] = {}

    def mark_invited(value: str) -> None:
        invited_checked["email"] = value

    domain_checked: dict[str, str] = {}

    def mark_domain(value: str) -> None:
        domain_checked["email"] = value

    monkeypatch.setattr(users_module, "verify_email_is_invited", mark_invited)
    monkeypatch.setattr(users_module, "verify_email_domain", mark_domain)
    email = "jwt-user@example.com"
    exp_value = 1_700_000_000
    payload: dict[str, Any] = {"email": email, "exp": exp_value}

    existing_user = MagicMock()
    existing_user.email = email
    existing_user.oidc_expiry = None
    existing_user.role.is_web_login.return_value = True  # type: ignore[attr-defined]

    manager_holder: dict[str, Any] = {}

    class StubUserManager:
        def __init__(self, _user_db: object) -> None:
            manager_holder["instance"] = self  # type: ignore[assignment]
            self.user_db = MagicMock()
            self.user_db.update = AsyncMock()

        async def get_by_email(self, email_arg: str) -> MagicMock:
            assert email_arg == email
            return existing_user

    monkeypatch.setattr(users_module, "UserManager", StubUserManager)
    monkeypatch.setattr(
        users_module,
        "SQLAlchemyUserAdminDB",
        lambda *args, **kwargs: MagicMock(),
    )

    result = await users_module._get_or_create_user_from_jwt(
        payload, MagicMock(), MagicMock()
    )

    assert result is existing_user
    assert invited_checked["email"] == email
    assert domain_checked["email"] == email
    expected_expiry = datetime.fromtimestamp(exp_value, tz=timezone.utc)
    instance = manager_holder["instance"]
    instance.user_db.update.assert_awaited_once_with(  # type: ignore[attr-defined]
        existing_user, {"oidc_expiry": expected_expiry}
    )
    assert existing_user.oidc_expiry == expected_expiry


@pytest.mark.asyncio
async def test_get_or_create_user_provisions_new_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand new JWT user should be provisioned automatically."""
    email = "new-user@example.com"
    payload = {"email": email}
    created_user = MagicMock()
    created_user.email = email
    created_user.oidc_expiry = None
    created_user.role.is_web_login.return_value = True  # type: ignore[attr-defined]

    monkeypatch.setattr(users_module, "TRACK_EXTERNAL_IDP_EXPIRY", False)
    monkeypatch.setattr(users_module, "generate_password", lambda: "TempPass123!")
    monkeypatch.setattr(users_module, "verify_email_is_invited", lambda _: None)
    monkeypatch.setattr(users_module, "verify_email_domain", lambda _: None)

    recorded: dict[str, Any] = {}

    class StubUserManager:
        def __init__(self, _user_db: object) -> None:
            recorded["instance"] = self
            self.user_db = MagicMock()
            self.user_db.update = AsyncMock()

        async def get_by_email(self, _email: str) -> MagicMock:
            raise users_module.exceptions.UserNotExists()

        async def create(self, user_create, safe=False, request=None):  # type: ignore[no-untyped-def]
            recorded["user_create"] = user_create
            recorded["request"] = request
            return created_user

    monkeypatch.setattr(users_module, "UserManager", StubUserManager)
    monkeypatch.setattr(
        users_module,
        "SQLAlchemyUserAdminDB",
        lambda *args, **kwargs: MagicMock(),
    )

    request = MagicMock()
    result = await users_module._get_or_create_user_from_jwt(
        payload, request, MagicMock()
    )

    assert result is created_user
    created_payload = recorded["user_create"]
    assert created_payload.email == email
    assert created_payload.is_verified is True
    assert recorded["request"] is request


@pytest.mark.asyncio
async def test_get_or_create_user_requires_email_claim() -> None:
    """Tokens without a usable email claim should be ignored."""
    result = await users_module._get_or_create_user_from_jwt(
        {}, MagicMock(), MagicMock()
    )
    assert result is None
