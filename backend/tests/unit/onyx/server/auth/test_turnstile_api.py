"""Unit tests for the Turnstile verify endpoint + middleware."""

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.auth import turnstile_api as turnstile_api_module
from onyx.server.auth.turnstile_api import router as turnstile_router
from onyx.server.auth.turnstile_api import TurnstileMiddleware

# ---------- helpers ----------


def build_app_with_middleware() -> FastAPI:
    """Build a minimal FastAPI app with the Turnstile router + middleware + a
    fake /auth/register route so we can observe whether the middleware lets
    requests through."""
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.add_middleware(TurnstileMiddleware)
    app.include_router(turnstile_router)

    @app.post("/auth/register")
    async def _register() -> dict[str, str]:
        return {"status": "created"}

    @app.get("/auth/oauth/callback")
    async def _oauth_callback() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/me")
    async def _me() -> dict[str, str]:
        return {"status": "not-guarded"}

    return app


# ---------- /auth/turnstile/verify endpoint ----------


def test_verify_endpoint_returns_ok_when_enforcement_off() -> None:
    """Dormant mode: endpoint returns ok without touching Cloudflare."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=False
    ):
        res = client.post("/auth/turnstile/verify", json={"token": "whatever"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    # No cookie issued in dormant mode.
    assert turnstile_api_module.TURNSTILE_COOKIE_NAME not in res.cookies


def test_verify_endpoint_sets_cookie_on_success() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with (
        patch.object(
            turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
        ),
        patch.object(
            turnstile_api_module,
            "verify_turnstile_token",
            AsyncMock(return_value=(True, None)),
        ),
    ):
        res = client.post("/auth/turnstile/verify", json={"token": "valid-token"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert turnstile_api_module.TURNSTILE_COOKIE_NAME in res.cookies


def test_verify_endpoint_raises_onyx_error_on_failure() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with (
        patch.object(
            turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
        ),
        patch.object(
            turnstile_api_module,
            "verify_turnstile_token",
            AsyncMock(return_value=(False, "invalid-input-response")),
        ),
    ):
        res = client.post("/auth/turnstile/verify", json={"token": "bad-token"})
    assert res.status_code == 403
    body = res.json()
    # Shape matches the global OnyxError handler: {error_code, detail}.
    assert body["error_code"] == "UNAUTHORIZED"
    assert "invalid-input-response" in body["detail"]


def test_verify_endpoint_rejects_missing_token() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    res = client.post("/auth/turnstile/verify", json={})
    # Pydantic validation failure from missing `token` field.
    assert res.status_code == 422


# ---------- TurnstileMiddleware ----------


def test_middleware_passes_through_when_enforcement_off() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=False
    ):
        res = client.post("/auth/register", json={"email": "x", "password": "y"})
    assert res.status_code == 200
    assert res.json() == {"status": "created"}


def test_middleware_blocks_guarded_path_without_cookie() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
    ):
        res = client.post("/auth/register", json={"email": "x", "password": "y"})
    assert res.status_code == 403
    body = res.json()
    assert body["error_code"] == "UNAUTHORIZED"
    assert "Turnstile challenge required" in body["detail"]


def test_middleware_blocks_oauth_callback_without_cookie() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
    ):
        res = client.get("/auth/oauth/callback")
    assert res.status_code == 403


def test_middleware_allows_guarded_path_with_valid_cookie() -> None:
    """A correctly-signed unexpired cookie lets the request reach the route."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
    ):
        # Issue a real signed cookie via the same helper the endpoint uses.
        cookie_value = turnstile_api_module.issue_turnstile_cookie_value()
        res = client.post(
            "/auth/register",
            json={"email": "x", "password": "y"},
            cookies={turnstile_api_module.TURNSTILE_COOKIE_NAME: cookie_value},
        )
    assert res.status_code == 200
    assert res.json() == {"status": "created"}


def test_middleware_rejects_tampered_cookie() -> None:
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
    ):
        res = client.post(
            "/auth/register",
            json={"email": "x", "password": "y"},
            cookies={turnstile_api_module.TURNSTILE_COOKIE_NAME: "9999999999.deadbeef"},
        )
    assert res.status_code == 403


def test_middleware_ignores_non_guarded_paths() -> None:
    """Endpoints outside GUARDED_SIGNUP_PATHS pass through regardless of cookie."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
    ):
        res = client.post("/me")
    assert res.status_code == 200


def test_middleware_skips_options_preflight() -> None:
    """CORS preflight must pass through even without a cookie."""
    app = build_app_with_middleware()
    client = TestClient(app)
    with patch.object(
        turnstile_api_module, "turnstile_enforcement_enabled", return_value=True
    ):
        # OPTIONS on a guarded path — middleware must let it through.
        res = client.options("/auth/register")
    # FastAPI's default handler for OPTIONS on a route that only defines POST
    # responds with 405. The key assertion is that Turnstile did NOT 403 it.
    assert res.status_code != 403


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
