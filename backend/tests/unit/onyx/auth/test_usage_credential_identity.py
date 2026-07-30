from typing import Any, cast

import pytest
from fastapi import Request

from onyx.auth import users
from onyx.db.models import User
from shared_configs.contextvars import UsageCredentialIdentity


def _bare_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def _no_oauth_refresh(*_: Any, **__: Any) -> None:
    return None


async def _resolve(request: Request, user: User | None) -> User | None:
    return await users._resolve_optional_user(
        request,
        cast(Any, None),
        user,
        cast(Any, None),
    )


@pytest.fixture(autouse=True)
def _patch_auth_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users, "_maybe_refresh_oauth_tokens", _no_oauth_refresh)
    monkeypatch.setattr(users, "JWT_PUBLIC_KEY_URL", None)


@pytest.mark.asyncio
async def test_cookie_session_user_is_session_credential() -> None:
    request = _bare_request()
    user = cast(User, object())

    assert await _resolve(request, user) is user
    assert request.state.usage_credential == UsageCredentialIdentity("session")


@pytest.mark.asyncio
async def test_unauthenticated_request_has_no_credential() -> None:
    request = _bare_request()

    assert await _resolve(request, None) is None
    assert getattr(request.state, "usage_credential", None) is None


@pytest.mark.asyncio
async def test_external_jwt_user_is_jwt_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jwt_user = cast(User, object())

    async def fake_check(*_: Any, **__: Any) -> User:
        return jwt_user

    monkeypatch.setattr(users, "_check_for_saml_and_jwt", fake_check)
    request = _bare_request()

    assert await _resolve(request, None) is jwt_user
    assert request.state.usage_credential == UsageCredentialIdentity("jwt")
