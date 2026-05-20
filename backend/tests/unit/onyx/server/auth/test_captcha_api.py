"""Unit tests for the reCAPTCHA OAuth verify endpoint + cookie middleware."""

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.auth.captcha import CaptchaVerificationError
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.auth import captcha_api as captcha_api_module
from onyx.server.auth.captcha_api import CaptchaCookieMiddleware
from onyx.server.auth.captcha_api import router as captcha_router


def build_app_with_middleware() -> FastAPI:
    """Minimal app with the middleware + router + fake OAuth callback route."""
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.add_middleware(CaptchaCookieMiddleware)
    app.include_router(captcha_router)

    @app.get("/auth/oauth/callback")
    async def _oauth_callback() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/auth/register")
    async def _register() -> dict[str, str]:
        # /auth/register is NOT gated by this middleware (it has its own
        # captcha enforcement in UserManager.create). Used here to prove the
        # middleware only touches /auth/oauth/callback.
        return {"status": "created"}

    @app.get("/me")
    async def _me() -> dict[str, str]:
        return {"status": "not-guarded"}

    return app


# ---------- /auth/captcha/oauth-verify endpoint ----------


def test_verify_endpoint_returns_ok_when_captcha_disabled() -> None:
    """Dormant mode: endpoint is a no-op, no cookie issued."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=False):
        res = client.post("/auth/captcha/oauth-verify", json={"token": "whatever"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    from onyx.auth.captcha import CAPTCHA_COOKIE_NAME

    assert CAPTCHA_COOKIE_NAME not in res.cookies


def test_verify_endpoint_sets_cookie_on_success() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            AsyncMock(return_value=None),
        ),
    ):
        res = client.post("/auth/captcha/oauth-verify", json={"token": "valid-token"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    from onyx.auth.captcha import CAPTCHA_COOKIE_NAME

    assert CAPTCHA_COOKIE_NAME in res.cookies


def test_verify_endpoint_raises_onyx_error_on_failure() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            AsyncMock(
                side_effect=CaptchaVerificationError(
                    "Captcha verification failed: invalid-input-response"
                )
            ),
        ),
    ):
        res = client.post("/auth/captcha/oauth-verify", json={"token": "bad-token"})
    assert res.status_code == 403
    body = res.json()
    assert body["error_code"] == "UNAUTHORIZED"
    assert "invalid-input-response" in body["detail"]


def test_verify_endpoint_rejects_missing_token() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    res = client.post("/auth/captcha/oauth-verify", json={})
    # Pydantic validation failure from missing `token`.
    assert res.status_code == 422


# ---------- CaptchaCookieMiddleware ----------


def test_middleware_passes_through_when_captcha_disabled() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=False):
        res = client.get("/auth/oauth/callback")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_middleware_blocks_oauth_callback_without_cookie() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=True):
        res = client.get("/auth/oauth/callback")
    assert res.status_code == 403
    body = res.json()
    assert body["error_code"] == "UNAUTHORIZED"
    assert "Captcha challenge required" in body["detail"]


def test_middleware_allows_oauth_callback_with_valid_cookie() -> None:
    """A correctly-signed unexpired cookie lets the OAuth callback through."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=True):
        cookie_value = captcha_api_module.issue_captcha_cookie_value()
        from onyx.auth.captcha import CAPTCHA_COOKIE_NAME

        res = client.get(
            "/auth/oauth/callback",
            cookies={CAPTCHA_COOKIE_NAME: cookie_value},
        )
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_middleware_clears_cookie_after_successful_callback() -> None:
    """One-time-use: cookie is deleted after the callback has been served so
    a replayed callback URL cannot re-enter without a fresh challenge."""
    app = build_app_with_middleware()
    client = TestClient(app)
    from onyx.auth.captcha import CAPTCHA_COOKIE_NAME

    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=True):
        cookie_value = captcha_api_module.issue_captcha_cookie_value()
        res = client.get(
            "/auth/oauth/callback",
            cookies={CAPTCHA_COOKIE_NAME: cookie_value},
        )
    assert res.status_code == 200
    set_cookie = res.headers.get("set-cookie", "")
    # Starlette's delete_cookie emits an expired Max-Age=0 Set-Cookie for the name.
    assert CAPTCHA_COOKIE_NAME in set_cookie
    assert (
        "Max-Age=0" in set_cookie or 'expires="Thu, 01 Jan 1970' in set_cookie.lower()
    )


def test_middleware_rejects_tampered_cookie() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    from onyx.auth.captcha import CAPTCHA_COOKIE_NAME

    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=True):
        res = client.get(
            "/auth/oauth/callback",
            cookies={CAPTCHA_COOKIE_NAME: "9999999999.deadbeef"},
        )
    assert res.status_code == 403


def test_middleware_ignores_register_path() -> None:
    """/auth/register has its own captcha enforcement in UserManager.create —
    the cookie middleware should NOT gate it."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=True):
        res = client.post("/auth/register", json={})
    assert res.status_code == 200


def test_middleware_ignores_unrelated_paths() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=True):
        res = client.get("/me")
    assert res.status_code == 200


def test_middleware_skips_options_preflight() -> None:
    """CORS preflight must pass through even without a cookie."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=True):
        res = client.options("/auth/oauth/callback")
    # Not 403: preflight passed the captcha gate.
    assert res.status_code != 403


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
