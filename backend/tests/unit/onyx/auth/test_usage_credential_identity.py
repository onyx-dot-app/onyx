from typing import Any, cast

import pytest
from fastapi import Request

from onyx.auth import users
from onyx.db.enums import PatType
from onyx.db.models import User
from onyx.db.pat import PatAuthResult
from onyx.server.security.store import _build_env_defaults
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


def _bare_request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request(
        {"type": "http", "method": "GET", "path": "/", "headers": headers or []}
    )


async def _no_oauth_refresh(*_: Any, **__: Any) -> None:
    return None


async def _resolve(request: Request, user: User | None) -> User | None:
    return await users._resolve_optional_user(
        request,
        cast(Any, None),
        user,
        cast(Any, None),
    )


def _point_settings_at(monkeypatch: pytest.MonkeyPatch, url: str | None) -> None:
    settings = _build_env_defaults().model_copy(update={"jwt_public_key_url": url})
    monkeypatch.setattr(users, "get_security_settings", lambda: settings)


@pytest.fixture(autouse=True)
def _patch_auth_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(users, "_maybe_refresh_oauth_tokens", _no_oauth_refresh)
    _point_settings_at(monkeypatch, None)


@pytest.mark.asyncio
async def test_cookie_session_user_is_session_credential() -> None:
    request = _bare_request()
    user = cast(User, object())

    assert await _resolve(request, user) is user
    assert request.state.usage_credential == UsageCredentialIdentity(
        UsageCredentialType.SESSION
    )


@pytest.mark.asyncio
async def test_unauthenticated_request_has_no_credential() -> None:
    request = _bare_request()

    assert await _resolve(request, None) is None
    assert (
        getattr(request.state, "usage_credential", None) is None  # ods: ignore[getattr]
    )


@pytest.mark.parametrize(
    "pat_type, expected_credential_type",
    [
        (PatType.USER, UsageCredentialType.PAT),
        (PatType.CRAFT, UsageCredentialType.CRAFT_PAT),
    ],
)
@pytest.mark.asyncio
async def test_pat_type_selects_credential_type(
    monkeypatch: pytest.MonkeyPatch,
    pat_type: PatType,
    expected_credential_type: UsageCredentialType,
) -> None:
    pat_user = cast(User, object())
    pat = PatAuthResult(
        user=pat_user,
        scopes=None,
        pat_id=7,
        pat_name="my-token",
        pat_display="onyx_pat_...abcd",
        pat_type=pat_type,
    )

    async def fake_resolve_pat(*_: Any, **__: Any) -> PatAuthResult:
        return pat

    monkeypatch.setattr(users, "get_hashed_pat_from_request", lambda _: "hashed")
    monkeypatch.setattr(users, "resolve_pat", fake_resolve_pat)
    request = _bare_request()

    assert await _resolve(request, None) is pat_user
    assert request.state.usage_credential == UsageCredentialIdentity(
        expected_credential_type, "7", "my-token", "onyx_pat_...abcd"
    )


@pytest.mark.asyncio
async def test_external_jwt_user_is_jwt_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drives the real _check_for_saml_and_jwt — stubbing it out tests nothing."""
    jwt_user = cast(User, object())

    async def fake_verify(_: str) -> dict[str, str]:
        return {"sub": "someone"}

    async def fake_get_or_create(*_: Any, **__: Any) -> User:
        return jwt_user

    _point_settings_at(monkeypatch, "https://idp.example/jwks")
    monkeypatch.setattr(users, "verify_jwt_token", fake_verify)
    monkeypatch.setattr(users, "_get_or_create_user_from_jwt", fake_get_or_create)
    request = _bare_request([(b"authorization", b"Bearer some-token")])

    assert await _resolve(request, None) is jwt_user
    assert request.state.usage_credential == UsageCredentialIdentity(
        UsageCredentialType.JWT
    )
