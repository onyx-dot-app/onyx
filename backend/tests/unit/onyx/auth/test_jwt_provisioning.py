from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from onyx.auth import users as users_module


def _stub_security_settings(
    monkeypatch: pytest.MonkeyPatch, *, track_external_idp_expiry: bool
) -> None:
    """Make get_security_settings() return a SecuritySettings with the
    given track_external_idp_expiry value (other fields use env defaults)."""
    from onyx.server.security.models import SecuritySettings
    from onyx.server.security.store import _build_env_defaults

    base = _build_env_defaults()
    stubbed = SecuritySettings(
        user_directory_admin_only=base.user_directory_admin_only,
        track_external_idp_expiry=track_external_idp_expiry,
        mask_credential_prefix=base.mask_credential_prefix,
        valid_email_domains=base.valid_email_domains,
        password_min_length=base.password_min_length,
        password_max_length=base.password_max_length,
        password_require_uppercase=base.password_require_uppercase,
        password_require_lowercase=base.password_require_lowercase,
        password_require_digit=base.password_require_digit,
        password_require_special_char=base.password_require_special_char,
    )
    monkeypatch.setattr(users_module, "get_security_settings", lambda: stubbed)


def test_extract_email_requires_valid_format() -> None:
    """Helper should validate email format before returning value."""
    assert users_module._extract_email_from_jwt({"email": "invalid@"}) is None
    result = users_module._extract_email_from_jwt(
        {"preferred_username": "ValidUser@Example.COM"}
    )
    assert result == "validuser@example.com"


@pytest.mark.asyncio
async def test_get_or_create_user_updates_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing web-login users should be returned and their expiry synced."""
    _stub_security_settings(monkeypatch, track_external_idp_expiry=True)
    invited_checked: dict[str, str] = {}

    def mark_invited(value: str) -> None:
        invited_checked["email"] = value

    domain_checked: dict[str, str] = {}

    def mark_domain(value: str, **_kw: Any) -> None:
        domain_checked["email"] = value

    monkeypatch.setattr(users_module, "verify_email_is_invited", mark_invited)
    monkeypatch.setattr(users_module, "verify_email_domain", mark_domain)
    email = "jwt-user@example.com"
    exp_value = 1_700_000_000
    payload: dict[str, Any] = {"email": email, "exp": exp_value}

    existing_user = MagicMock()
    existing_user.email = email
    existing_user.oidc_expiry = None
    existing_user.role.is_web_login.return_value = True

    manager_holder: dict[str, Any] = {}

    class StubUserManager:
        def __init__(self, _user_db: object) -> None:
            manager_holder["instance"] = self
            self.user_db = MagicMock()
            self.user_db.update = AsyncMock()

        async def get_by_email(self, email_arg: str) -> MagicMock:
            assert email_arg == email
            return existing_user

    monkeypatch.setattr(users_module, "UserManager", StubUserManager)
    monkeypatch.setattr(
        users_module,
        "SQLAlchemyUserAdminDB",
        lambda *args, **kwargs: MagicMock(),  # noqa: ARG005
    )

    result = await users_module._get_or_create_user_from_jwt(
        payload, MagicMock(), MagicMock()
    )

    assert result is existing_user
    assert invited_checked["email"] == email
    assert domain_checked["email"] == email
    expected_expiry = datetime.fromtimestamp(exp_value, tz=timezone.utc)
    instance = manager_holder["instance"]
    instance.user_db.update.assert_awaited_once_with(
        existing_user, {"oidc_expiry": expected_expiry}
    )
    assert existing_user.oidc_expiry == expected_expiry


@pytest.mark.asyncio
async def test_get_or_create_user_skips_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inactive users should not be re-authenticated via JWT."""
    _stub_security_settings(monkeypatch, track_external_idp_expiry=True)
    monkeypatch.setattr(users_module, "verify_email_is_invited", lambda _: None)
    monkeypatch.setattr(users_module, "verify_email_domain", lambda *_a, **_kw: None)

    email = "inactive@example.com"
    payload: dict[str, Any] = {"email": email}

    existing_user = MagicMock()
    existing_user.email = email
    existing_user.is_active = False
    existing_user.role.is_web_login.return_value = True

    class StubUserManager:
        def __init__(self, _user_db: object) -> None:
            self.user_db = MagicMock()
            self.user_db.update = AsyncMock()

        async def get_by_email(self, email_arg: str) -> MagicMock:
            assert email_arg == email
            return existing_user

    monkeypatch.setattr(users_module, "UserManager", StubUserManager)
    monkeypatch.setattr(
        users_module,
        "SQLAlchemyUserAdminDB",
        lambda *args, **kwargs: MagicMock(),  # noqa: ARG005
    )

    result = await users_module._get_or_create_user_from_jwt(
        payload, MagicMock(), MagicMock()
    )

    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_user_handles_race_conditions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If provisioning races, newly inactive users should still be blocked."""
    _stub_security_settings(monkeypatch, track_external_idp_expiry=True)
    monkeypatch.setattr(users_module, "verify_email_is_invited", lambda _: None)
    monkeypatch.setattr(users_module, "verify_email_domain", lambda *_a, **_kw: None)

    email = "race@example.com"
    payload: dict[str, Any] = {"email": email}

    inactive_user = MagicMock()
    inactive_user.email = email
    inactive_user.is_active = False
    inactive_user.role.is_web_login.return_value = True

    class StubUserManager:
        def __init__(self, _user_db: object) -> None:
            self.user_db = MagicMock()
            self.user_db.update = AsyncMock()
            self.get_calls = 0

        async def get_by_email(self, email_arg: str) -> MagicMock:
            assert email_arg == email
            if self.get_calls == 0:
                self.get_calls += 1
                raise users_module.exceptions.UserNotExists()
            self.get_calls += 1
            return inactive_user

        async def create(self, *args: Any, **kwargs: Any) -> MagicMock:  # noqa: ARG002
            raise users_module.exceptions.UserAlreadyExists()

    monkeypatch.setattr(users_module, "UserManager", StubUserManager)
    monkeypatch.setattr(
        users_module,
        "SQLAlchemyUserAdminDB",
        lambda *args, **kwargs: MagicMock(),  # noqa: ARG005
    )

    result = await users_module._get_or_create_user_from_jwt(
        payload, MagicMock(), MagicMock()
    )

    assert result is None


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
    created_user.role.is_web_login.return_value = True

    _stub_security_settings(monkeypatch, track_external_idp_expiry=False)
    monkeypatch.setattr(users_module, "generate_password", lambda: "TempPass123!")
    monkeypatch.setattr(users_module, "verify_email_is_invited", lambda _: None)
    monkeypatch.setattr(users_module, "verify_email_domain", lambda *_a, **_kw: None)

    recorded: dict[str, Any] = {}

    class StubUserManager:
        def __init__(self, _user_db: object) -> None:
            recorded["instance"] = self
            self.user_db = MagicMock()
            self.user_db.update = AsyncMock()

        async def get_by_email(self, _email: str) -> MagicMock:
            raise users_module.exceptions.UserNotExists()

        async def create(self, user_create, safe=False, request=None):  # noqa: ARG002
            recorded["user_create"] = user_create
            recorded["request"] = request
            return created_user

    monkeypatch.setattr(users_module, "UserManager", StubUserManager)
    monkeypatch.setattr(
        users_module,
        "SQLAlchemyUserAdminDB",
        lambda *args, **kwargs: MagicMock(),  # noqa: ARG005
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
