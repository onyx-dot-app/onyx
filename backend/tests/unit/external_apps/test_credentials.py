"""Header rendering and source OpenAPI authentication contracts."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.auth import oauth_token_manager
from onyx.auth.oauth_token_manager import OAuthTokenManager
from onyx.db.models import (
    ExternalApp,
    OAuthAccount,
    OAuthConfig,
    OAuthUserToken,
    Tool,
    User,
)
from onyx.external_apps import credentials
from onyx.external_apps.credentials import (
    ExternalAppCredentialsError,
    build_auth_headers,
    resolve_injection_headers,
)
from onyx.utils.sensitive import make_mock_sensitive_value


def test_fills_placeholder_from_credentials() -> None:
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}"},
        {"access_token": "xoxb-123"},
    )
    assert headers == {"Authorization": "Bearer xoxb-123"}


def test_omits_header_with_unfilled_placeholder() -> None:
    # The token isn't available -> the header is dropped, not half-rendered.
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}", "X-Static": "always"},
        {},
    )
    assert headers == {"X-Static": "always"}


def test_static_header_needs_no_credentials() -> None:
    assert build_auth_headers({"X-Api-Version": "2025-01"}, {}) == {
        "X-Api-Version": "2025-01"
    }


def test_multiple_placeholders_all_required() -> None:
    template = {"Authorization": "{scheme} {token}"}
    assert build_auth_headers(template, {"scheme": "Bearer"}) == {}  # token missing
    assert build_auth_headers(template, {"scheme": "Bearer", "token": "t"}) == {
        "Authorization": "Bearer t"
    }


def test_credential_value_with_braces_is_not_reinterpreted() -> None:
    # A value containing braces must be substituted literally, not re-formatted.
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}"},
        {"access_token": "ab{cd}ef"},
    )
    assert headers == {"Authorization": "Bearer ab{cd}ef"}


def test_extra_credentials_are_ignored() -> None:
    headers = build_auth_headers(
        {"Authorization": "Bearer {access_token}"},
        {"access_token": "t", "client_secret": "unused"},
    )
    assert headers == {"Authorization": "Bearer t"}


def test_non_string_template_value_skipped() -> None:
    headers = build_auth_headers(
        {"Authorization": "Bearer {t}", "Bad": 123},
        {"t": "x"},
    )
    assert headers == {"Authorization": "Bearer x"}


def test_attribute_or_index_access_skips_only_the_bad_header() -> None:
    # `{t.x}` / `{t[x]}` raise AttributeError / TypeError during render; they
    # must skip only that header, not abort the whole render.
    headers = build_auth_headers(
        {
            "Authorization": "Bearer {t}",
            "Attr": "{t.value}",
            "Index": "{t[id]}",
        },
        {"t": "x"},
    )
    assert headers == {"Authorization": "Bearer x"}


def _openapi_app(*, oauth: bool = False, passthrough: bool = False) -> ExternalApp:
    tool = Tool(id=7, name="Action", passthrough_auth=passthrough)
    if oauth:
        tool.oauth_config_id = 9
        tool.oauth_config = OAuthConfig(id=9, name="OAuth")
    return ExternalApp(
        id=3,
        name="Action",
        enabled=True,
        openapi_tool_id=tool.id,
        openapi_tool=tool,
        auth_template={"X-Workspace": "{header_0}", "authorization": "{header_1}"},
        organization_credentials=make_mock_sensitive_value(
            {
                "header_0": "workspace",
                "header_1": "Bearer shared-static",
            }
        ),
    )


@pytest.mark.parametrize(
    "token",
    [
        {"access_token": "live", "expires_at": 10_000},
        {"access_token": "old", "expires_at": 1, "refresh_token": "refresh"},
    ],
)
def test_oauth_availability_does_not_refresh(
    monkeypatch: pytest.MonkeyPatch, token: dict[str, Any]
) -> None:
    monkeypatch.setattr(oauth_token_manager.time, "time", lambda: 100)
    row = OAuthUserToken(token_data=token)
    monkeypatch.setattr(oauth_token_manager, "get_user_oauth_token", lambda *_a: row)
    refresh = MagicMock()
    monkeypatch.setattr(OAuthTokenManager, "refresh_token", refresh)
    manager = OAuthTokenManager(OAuthConfig(id=9), uuid4(), MagicMock())
    assert manager.has_usable_access_token()
    refresh.assert_not_called()


@pytest.mark.parametrize(
    "token", [None, {}, {"access_token": ""}, {"access_token": "old", "expires_at": 1}]
)
def test_oauth_missing_or_expired_unrefreshable_token_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, token: dict[str, Any] | None
) -> None:
    monkeypatch.setattr(oauth_token_manager.time, "time", lambda: 100)
    row = OAuthUserToken(token_data=token) if token is not None else None
    monkeypatch.setattr(oauth_token_manager, "get_user_oauth_token", lambda *_a: row)
    assert not OAuthTokenManager(
        OAuthConfig(id=9), uuid4(), MagicMock()
    ).has_usable_access_token()


def test_openapi_injection_refreshes_source_oauth_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _openapi_app(oauth=True, passthrough=True)
    monkeypatch.setattr(credentials, "get_external_app_by_id", lambda *_a: app)
    row = OAuthUserToken(
        token_data={"access_token": "old", "expires_at": 1, "refresh_token": "refresh"}
    )
    monkeypatch.setattr(oauth_token_manager, "get_user_oauth_token", lambda *_a: row)
    refresh = MagicMock(return_value="new-per-user-token")
    monkeypatch.setattr(OAuthTokenManager, "refresh_token", refresh)
    user = User(id=uuid4(), oauth_accounts=[])
    user_lookup = MagicMock(return_value=user)
    monkeypatch.setattr(credentials, "fetch_user_by_id", user_lookup)
    assert resolve_injection_headers(MagicMock(), app.id, user.id) == {
        "X-Workspace": "workspace",
        "Authorization": "Bearer new-per-user-token",
    }
    refresh.assert_called_once_with(row)
    user_lookup.assert_called_once()


@pytest.mark.parametrize("passthrough", [False, True])
def test_missing_oauth_token_cannot_fall_back_to_static_headers(
    monkeypatch: pytest.MonkeyPatch,
    passthrough: bool,
) -> None:
    app = _openapi_app(oauth=True, passthrough=passthrough)
    monkeypatch.setattr(credentials, "get_external_app_by_id", lambda *_a: app)
    monkeypatch.setattr(oauth_token_manager, "get_user_oauth_token", lambda *_a: None)
    monkeypatch.setattr(credentials, "fetch_user_by_id", lambda *_a: User(id=uuid4()))
    with pytest.raises(ExternalAppCredentialsError, match="Connect or reconnect"):
        resolve_injection_headers(MagicMock(), app.id, uuid4())


def test_passthrough_uses_each_sandbox_users_login_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _openapi_app(passthrough=True)
    monkeypatch.setattr(credentials, "get_external_app_by_id", lambda *_a: app)
    alice = User(id=uuid4(), oauth_accounts=[OAuthAccount(access_token="alice-token")])
    bob = User(id=uuid4(), oauth_accounts=[OAuthAccount(access_token="bob-token")])
    users = {alice.id: alice, bob.id: bob}
    monkeypatch.setattr(
        credentials, "fetch_user_by_id", lambda _db, user_id: users[user_id]
    )
    for user, token in [(alice, "alice-token"), (bob, "bob-token")]:
        headers = resolve_injection_headers(MagicMock(), app.id, user.id)
        assert headers["Authorization"] == f"Bearer {token}"
        assert "authorization" not in headers


def test_missing_passthrough_token_cannot_fall_back_to_static_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _openapi_app(passthrough=True)
    user = User(id=uuid4(), oauth_accounts=[])
    monkeypatch.setattr(credentials, "get_external_app_by_id", lambda *_a: app)
    monkeypatch.setattr(credentials, "fetch_user_by_id", lambda *_a: user)
    with pytest.raises(ExternalAppCredentialsError, match="Sign in to Onyx"):
        resolve_injection_headers(MagicMock(), app.id, user.id)
