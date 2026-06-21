"""External-dependency-unit tests for the mobile SSO bridge on the shared OAuth
router (`get_oauth_router`), the highest-blast-radius change in the mobile-auth
work — it edits code that web Google login also runs.

Uses a stub OAuth client + mocked strategy/backend (à la `test_oidc_pkce.py`),
but a REAL Redis (the one-time code is actually stored/redeemed). Google runs the
non-PKCE branch (`enable_pkce=False`), so that is what we exercise here.

Coverage:
  * authorize folds the guarded mobile params into the *signed* state (and is a
    no-op for web callers — the regression guard against drift),
  * the callback's `client=="mobile"` branch returns a 302 to the deep link
    carrying a single-use, PKCE-bound code and NO web auth cookie,
  * the web cookie path is byte-for-byte unchanged when the marker is absent,
  * disallowed redirect URI / missing PKCE challenge are rejected at
    authorize-time (400), before the IdP round-trip.
"""

import asyncio
from typing import Any
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI
from fastapi import Response
from fastapi.testclient import TestClient
from fastapi_users.authentication import AuthenticationBackend
from fastapi_users.authentication import CookieTransport
from fastapi_users.jwt import decode_jwt
from httpx_oauth.oauth2 import BaseOAuth2

from onyx.auth.mobile_sso.code_store import consume_sso_code
from onyx.auth.users import generate_pkce_pair
from onyx.auth.users import get_oauth_router
from onyx.auth.users import STATE_TOKEN_AUDIENCE
from onyx.error_handling.exceptions import register_onyx_exception_handlers

_STATE_SECRET = "test-secret"
_MINTED_TOKEN = "minted_session_token"
_ALLOWED_REDIRECT = "onyx://auth/callback"


class _StubOAuthClient:
    def __init__(self) -> None:
        self.name = "google"
        self.authorization_calls: list[dict[str, Any]] = []
        self.access_token_calls: list[dict[str, Any]] = []

    async def get_authorization_url(
        self,
        redirect_uri: str,
        state: str | None = None,
        scope: list[str] | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ) -> str:
        self.authorization_calls.append(
            {
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": scope,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
            }
        )
        return f"https://accounts.google.com/o/oauth2/auth?state={state}"

    async def get_access_token(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict[str, str | int]:
        self.access_token_calls.append(
            {"code": code, "redirect_uri": redirect_uri, "code_verifier": code_verifier}
        )
        return {
            "access_token": "google_access_token",
            "refresh_token": "google_refresh_token",
            "expires_at": 1730000000,
        }

    async def get_id_email(self, _access_token: str) -> tuple[str, str | None]:
        return ("google_account_id", "mobile_user@example.com")


def _build_test_client(
    enable_pkce: bool = False,
) -> tuple[TestClient, _StubOAuthClient, AsyncMock, MagicMock]:
    oauth_client = _StubOAuthClient()
    transport = CookieTransport(cookie_name="testsession")

    # The strategy mints the bearer credential (issue_session_credential ->
    # strategy.write_token). Mock it so we get a deterministic token without a
    # real session backend.
    strategy = MagicMock()
    strategy.write_token = AsyncMock(return_value=_MINTED_TOKEN)

    async def get_strategy() -> MagicMock:
        return strategy

    backend = AuthenticationBackend(
        name="test_backend",
        transport=transport,
        get_strategy=get_strategy,
    )

    login_response = Response(status_code=302)
    login_response.headers["location"] = "/app"
    login_response.set_cookie("testsession", "session-token")
    login_mock = AsyncMock(return_value=login_response)
    backend.login = login_mock  # ty: ignore[invalid-assignment]

    user = MagicMock()
    user.is_active = True
    user_manager = MagicMock()
    user_manager.oauth_callback = AsyncMock(return_value=user)
    user_manager.on_after_login = AsyncMock()

    async def get_user_manager() -> MagicMock:
        return user_manager

    # enable_pkce=False mirrors Google's real config; OIDC (enable_pkce=True)
    # shares this router and the same mobile branch, so we exercise both.
    router = get_oauth_router(
        oauth_client=cast(BaseOAuth2[Any], oauth_client),
        backend=backend,
        get_user_manager=get_user_manager,
        state_secret=_STATE_SECRET,
        redirect_url="http://localhost/auth/oauth/callback",
        associate_by_email=True,
        is_verified_by_default=True,
        enable_pkce=enable_pkce,
    )
    app = FastAPI()
    app.include_router(router, prefix="/auth/oauth")
    register_onyx_exception_handlers(app)

    client = TestClient(app, raise_server_exceptions=False)
    return client, oauth_client, login_mock, user_manager


def _authorize_and_get_state(client: TestClient, params: dict[str, str]) -> str:
    response = client.get("/auth/oauth/authorize", params=params)
    assert response.status_code == 200
    auth_url = response.json()["authorization_url"]
    return parse_qs(urlparse(auth_url).query)["state"][0]


def _callback(client: TestClient, state: str) -> httpx.Response:
    # Every callback test resolves the tenant the same way; centralize the patch.
    with patch(
        "onyx.auth.users.fetch_ee_implementation_or_noop",
        return_value=lambda _email: "tenant_1",
    ):
        return client.get(
            "/auth/oauth/callback",
            params={"code": "idp_code", "state": state},
            follow_redirects=False,
        )


def test_authorize_folds_mobile_params_into_signed_state() -> None:
    client, _, _, _ = _build_test_client()
    _, challenge = generate_pkce_pair()

    state = _authorize_and_get_state(
        client,
        {
            "mobile_redirect_uri": _ALLOWED_REDIRECT,
            "app_state": "appstate-xyz",
            "app_code_challenge": challenge,
        },
    )

    decoded = decode_jwt(state, _STATE_SECRET, [STATE_TOKEN_AUDIENCE])
    assert decoded["client"] == "mobile"
    assert decoded["app_redirect_uri"] == _ALLOWED_REDIRECT
    assert decoded["app_state"] == "appstate-xyz"
    assert decoded["app_code_challenge"] == challenge


def test_authorize_without_mobile_params_leaves_state_unmarked() -> None:
    # Web-flow regression: the signed state must not gain any mobile keys.
    client, _, _, _ = _build_test_client()

    state = _authorize_and_get_state(client, {})

    decoded = decode_jwt(state, _STATE_SECRET, [STATE_TOKEN_AUDIENCE])
    assert "client" not in decoded
    assert "app_redirect_uri" not in decoded
    assert "app_code_challenge" not in decoded


def test_mobile_callback_returns_deep_link_with_consumable_code() -> None:
    client, _, login_mock, _ = _build_test_client()
    verifier, challenge = generate_pkce_pair()
    state = _authorize_and_get_state(
        client,
        {
            "mobile_redirect_uri": _ALLOWED_REDIRECT,
            "app_state": "roundtrip-state",
            "app_code_challenge": challenge,
        },
    )

    response = _callback(client, state)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{_ALLOWED_REDIRECT}?")

    query = parse_qs(urlparse(location).query)
    assert query["state"][0] == "roundtrip-state"
    code = query["code"][0]

    # The deep link must NOT carry the token, and no web auth cookie is set.
    assert "access_token" not in query
    assert "testsession" not in response.cookies
    login_mock.assert_not_awaited()

    # The code redeems exactly once, only with the matching verifier.
    assert asyncio.run(consume_sso_code(code, verifier)) == _MINTED_TOKEN
    assert asyncio.run(consume_sso_code(code, verifier)) is None


def test_web_callback_unchanged_when_marker_absent() -> None:
    # The web cookie login path must be untouched by the mobile branch.
    client, _, login_mock, user_manager = _build_test_client()
    state = _authorize_and_get_state(client, {})

    response = _callback(client, state)

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert "testsession" in response.cookies
    login_mock.assert_awaited_once()
    user_manager.oauth_callback.assert_awaited_once()


def test_authorize_rejects_disallowed_redirect_uri() -> None:
    # Fail fast at authorize-time — before the IdP round-trip — for a redirect
    # URI that isn't allowlisted, so no signed state is ever minted for it.
    client, _, login_mock, _ = _build_test_client()
    _, challenge = generate_pkce_pair()
    response = client.get(
        "/auth/oauth/authorize",
        params={
            "mobile_redirect_uri": "https://evil.example.com/callback",
            "app_state": "s",
            "app_code_challenge": challenge,
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    login_mock.assert_not_awaited()


def test_authorize_rejects_missing_pkce_challenge() -> None:
    # Mobile SSO is PKCE-only — reject at authorize-time rather than deferring the
    # failure to the callback (no silent fallback to a non-PKCE code).
    client, _, login_mock, _ = _build_test_client()
    response = client.get(
        "/auth/oauth/authorize",
        params={
            "mobile_redirect_uri": _ALLOWED_REDIRECT,
            "app_state": "s",
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    login_mock.assert_not_awaited()


def test_authorize_pkce_provider_rejects_missing_challenge() -> None:
    # Same authorize-time rejection on a PKCE provider (OIDC); the raise happens
    # before any IdP-leg PKCE cookie is issued.
    client, _, login_mock, _ = _build_test_client(enable_pkce=True)
    response = client.get(
        "/auth/oauth/authorize",
        params={
            "mobile_redirect_uri": _ALLOWED_REDIRECT,
            "app_state": "s",
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    login_mock.assert_not_awaited()


# The mobile branch in the shared complete_login_flow also runs the success path
# for PKCE providers (OIDC), which share this router and the same mobile branch.


def test_mobile_callback_pkce_path_returns_deep_link_with_consumable_code() -> None:
    client, _, login_mock, _ = _build_test_client(enable_pkce=True)
    verifier, challenge = generate_pkce_pair()
    # authorize sets the IdP-leg PKCE verifier cookie (carried by the client).
    state = _authorize_and_get_state(
        client,
        {
            "mobile_redirect_uri": _ALLOWED_REDIRECT,
            "app_state": "pkce-roundtrip",
            "app_code_challenge": challenge,
        },
    )

    response = _callback(client, state)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{_ALLOWED_REDIRECT}?")
    query = parse_qs(urlparse(location).query)
    assert query["state"][0] == "pkce-roundtrip"
    assert "access_token" not in query
    assert "testsession" not in response.cookies
    login_mock.assert_not_awaited()
    assert asyncio.run(consume_sso_code(query["code"][0], verifier)) == _MINTED_TOKEN
