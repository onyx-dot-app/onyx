from typing import Any
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi import Response
from fastapi.testclient import TestClient
from fastapi_users.authentication import AuthenticationBackend
from fastapi_users.authentication import CookieTransport
from fastapi_users.jwt import generate_jwt
from httpx_oauth.oauth2 import BaseOAuth2
from httpx_oauth.oauth2 import GetAccessTokenError

from onyx.auth.users import CSRF_TOKEN_COOKIE_NAME
from onyx.auth.users import CSRF_TOKEN_KEY
from onyx.auth.users import get_oauth_router
from onyx.auth.users import get_pkce_cookie_name
from onyx.auth.users import PKCE_COOKIE_NAME_PREFIX
from onyx.auth.users import STATE_TOKEN_AUDIENCE
from onyx.error_handling.exceptions import register_onyx_exception_handlers


class _StubOAuthClient:
    def __init__(self) -> None:
        self.name = "openid"
        self.authorization_calls: list[dict[str, str | list[str] | None]] = []
        self.access_token_calls: list[dict[str, str | None]] = []

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
        return f"https://idp.example.com/authorize?state={state}"

    async def get_access_token(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict[str, str | int]:
        self.access_token_calls.append(
            {
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        return {
            "access_token": "oidc_access_token",
            "refresh_token": "oidc_refresh_token",
            "expires_at": 1730000000,
        }

    async def get_id_email(self, _access_token: str) -> tuple[str, str | None]:
        return ("oidc_account_id", "oidc_user@example.com")


def _build_test_client(
    enable_pkce: bool,
    login_status_code: int = 302,
) -> tuple[TestClient, _StubOAuthClient, MagicMock]:
    oauth_client = _StubOAuthClient()
    transport = CookieTransport(cookie_name="testsession")

    async def get_strategy() -> MagicMock:
        return MagicMock()

    backend = AuthenticationBackend(
        name="test_backend",
        transport=transport,
        get_strategy=get_strategy,
    )

    login_response = Response(status_code=login_status_code)
    if login_status_code in {301, 302, 303, 307, 308}:
        login_response.headers["location"] = "/app"
    login_response.set_cookie("testsession", "session-token")
    backend.login = AsyncMock(return_value=login_response)  # type: ignore[method-assign]

    user = MagicMock()
    user.is_active = True
    user_manager = MagicMock()
    user_manager.oauth_callback = AsyncMock(return_value=user)
    user_manager.on_after_login = AsyncMock()

    async def get_user_manager() -> MagicMock:
        return user_manager

    router = get_oauth_router(
        oauth_client=cast(BaseOAuth2[Any], oauth_client),
        backend=backend,
        get_user_manager=get_user_manager,
        state_secret="test-secret",
        redirect_url="http://localhost/auth/oidc/callback",
        associate_by_email=True,
        is_verified_by_default=True,
        enable_pkce=enable_pkce,
    )
    app = FastAPI()
    app.include_router(router, prefix="/auth/oidc")
    register_onyx_exception_handlers(app)

    client = TestClient(app, raise_server_exceptions=False)
    return client, oauth_client, user_manager


def _extract_state_from_authorize_response(response: Any) -> str:
    auth_url = response.json()["authorization_url"]
    return parse_qs(urlparse(auth_url).query)["state"][0]


def test_oidc_authorize_omits_pkce_when_flag_disabled() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=False)

    response = client.get("/auth/oidc/authorize")

    assert response.status_code == 200
    assert oauth_client.authorization_calls[0]["code_challenge"] is None
    assert oauth_client.authorization_calls[0]["code_challenge_method"] is None
    assert "fastapiusersoauthcsrf" in response.cookies.keys()
    assert not any(
        key.startswith(PKCE_COOKIE_NAME_PREFIX) for key in response.cookies.keys()
    )


def test_oidc_authorize_adds_pkce_when_flag_enabled() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)

    response = client.get("/auth/oidc/authorize")

    assert response.status_code == 200
    assert oauth_client.authorization_calls[0]["code_challenge"] is not None
    assert oauth_client.authorization_calls[0]["code_challenge_method"] == "S256"
    assert any(
        key.startswith(PKCE_COOKIE_NAME_PREFIX) for key in response.cookies.keys()
    )


def test_oidc_callback_fails_when_pkce_cookie_missing() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    for key in list(client.cookies.keys()):
        if key.startswith(PKCE_COOKIE_NAME_PREFIX):
            del client.cookies[key]

    response = client.get(
        "/auth/oidc/callback", params={"code": "abc123", "state": state}
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert oauth_client.access_token_calls == []
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_rejects_bad_state_before_token_exchange() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)
    client.get("/auth/oidc/authorize")
    tampered_state = "not-a-valid-state-jwt"
    client.cookies.set(get_pkce_cookie_name(tampered_state), "verifier123")

    response = client.get(
        "/auth/oidc/callback", params={"code": "abc123", "state": tampered_state}
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert oauth_client.access_token_calls == []
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_rejects_wrongly_signed_state_before_token_exchange() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)
    client.get("/auth/oidc/authorize")
    csrf_token = client.cookies.get(CSRF_TOKEN_COOKIE_NAME)
    assert csrf_token is not None
    tampered_state = generate_jwt(
        {
            "aud": STATE_TOKEN_AUDIENCE,
            CSRF_TOKEN_KEY: csrf_token,
        },
        "wrong-secret",
        3600,
    )
    client.cookies.set(get_pkce_cookie_name(tampered_state), "verifier123")

    response = client.get(
        "/auth/oidc/callback",
        params={"code": "abc123", "state": tampered_state},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["detail"] == "ACCESS_TOKEN_DECODE_ERROR"
    assert oauth_client.access_token_calls == []
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_rejects_csrf_mismatch_in_pkce_path() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    # Keep PKCE verifier cookie intact, but invalidate CSRF match against state JWT.
    client.cookies.set("fastapiusersoauthcsrf", "wrong-csrf-token")

    response = client.get(
        "/auth/oidc/callback",
        params={"code": "abc123", "state": state},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert oauth_client.access_token_calls == []
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_get_access_token_error_is_400() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)
    with patch.object(
        oauth_client,
        "get_access_token",
        AsyncMock(side_effect=GetAccessTokenError("token exchange failed")),
    ):
        response = client.get(
            "/auth/oidc/callback", params={"code": "abc123", "state": state}
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["detail"] == "Authorization code exchange failed"
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_cleans_pkce_cookie_on_idp_error_with_state() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    response = client.get(
        "/auth/oidc/callback",
        params={"error": "access_denied", "state": state},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert oauth_client.access_token_calls == []
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_cleans_pkce_cookie_on_missing_email() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=True)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    with patch.object(
        oauth_client, "get_id_email", AsyncMock(return_value=("oidc_account_id", None))
    ):
        response = client.get(
            "/auth/oidc/callback", params={"code": "abc123", "state": state}
        )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_uses_code_verifier_when_pkce_enabled() -> None:
    client, oauth_client, user_manager = _build_test_client(enable_pkce=True)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    with patch(
        "onyx.auth.users.fetch_ee_implementation_or_noop",
        return_value=lambda _email: "tenant_1",
    ):
        response = client.get(
            "/auth/oidc/callback",
            params={"code": "abc123", "state": state},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers.get("location") == "/"
    assert oauth_client.access_token_calls[0]["code_verifier"] is not None
    user_manager.oauth_callback.assert_awaited_once()
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_works_without_pkce_when_flag_disabled() -> None:
    client, oauth_client, user_manager = _build_test_client(enable_pkce=False)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    with patch(
        "onyx.auth.users.fetch_ee_implementation_or_noop",
        return_value=lambda _email: "tenant_1",
    ):
        response = client.get(
            "/auth/oidc/callback",
            params={"code": "abc123", "state": state},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert oauth_client.access_token_calls[0]["code_verifier"] is None
    user_manager.oauth_callback.assert_awaited_once()


def test_oidc_callback_pkce_preserves_redirect_when_backend_login_is_non_redirect() -> (
    None
):
    client, oauth_client, user_manager = _build_test_client(
        enable_pkce=True,
        login_status_code=200,
    )
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    with patch(
        "onyx.auth.users.fetch_ee_implementation_or_noop",
        return_value=lambda _email: "tenant_1",
    ):
        response = client.get(
            "/auth/oidc/callback",
            params={"code": "abc123", "state": state},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers.get("location") == "/"
    assert oauth_client.access_token_calls[0]["code_verifier"] is not None
    user_manager.oauth_callback.assert_awaited_once()
    assert "Max-Age=0" in response.headers.get("set-cookie", "")


def test_oidc_callback_non_pkce_rejects_csrf_mismatch() -> None:
    client, oauth_client, _ = _build_test_client(enable_pkce=False)
    authorize_response = client.get("/auth/oidc/authorize")
    state = _extract_state_from_authorize_response(authorize_response)

    client.cookies.set(CSRF_TOKEN_COOKIE_NAME, "wrong-csrf-token")

    response = client.get(
        "/auth/oidc/callback",
        params={"code": "abc123", "state": state},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["detail"] == "OAUTH_INVALID_STATE"
    # NOTE: In the non-PKCE path, oauth2_authorize_callback exchanges the code
    # before route-body CSRF validation runs. This is a known ordering trade-off.
    assert oauth_client.access_token_calls
