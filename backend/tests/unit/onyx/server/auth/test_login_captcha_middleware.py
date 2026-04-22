"""Unit tests for LoginCaptchaMiddleware."""

from unittest.mock import AsyncMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from onyx.auth.captcha import CaptchaAction
from onyx.auth.captcha import CaptchaVerificationError
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.auth import captcha_api as captcha_api_module
from onyx.server.auth.captcha_api import LoginCaptchaMiddleware


def build_app() -> FastAPI:
    app = FastAPI()
    register_onyx_exception_handlers(app)
    app.add_middleware(LoginCaptchaMiddleware)

    @app.post("/auth/login")
    async def _login() -> dict[str, str]:
        return {"status": "logged-in"}

    @app.post("/auth/register")
    async def _register() -> dict[str, str]:
        return {"status": "created"}

    @app.get("/auth/login")
    async def _login_get() -> dict[str, str]:
        return {"status": "get-ignored"}

    return app


def test_passes_through_when_captcha_disabled() -> None:
    app = build_app()
    client = TestClient(app)
    with patch.object(captcha_api_module, "is_captcha_enabled", return_value=False):
        res = client.post("/auth/login")
    assert res.status_code == 200
    assert res.json() == {"status": "logged-in"}


def test_rejects_when_header_missing() -> None:
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(
                side_effect=CaptchaVerificationError(
                    "Captcha verification failed: Captcha token is required"
                )
            ),
        ),
    ):
        res = client.post("/auth/login")
    assert res.status_code == 403
    assert "Captcha" in res.json()["detail"]


def test_rejects_on_bad_token() -> None:
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(
                side_effect=CaptchaVerificationError(
                    "Captcha verification failed: AUTOMATION"
                )
            ),
        ) as verify_mock,
    ):
        res = client.post("/auth/login", headers={"X-Captcha-Token": "bad-token"})
    assert res.status_code == 403
    verify_mock.assert_awaited_once_with("bad-token", CaptchaAction.LOGIN)


def test_passes_on_valid_token() -> None:
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(return_value=None),
        ) as verify_mock,
    ):
        res = client.post("/auth/login", headers={"X-Captcha-Token": "good-token"})
    assert res.status_code == 200
    verify_mock.assert_awaited_once_with("good-token", CaptchaAction.LOGIN)


def test_does_not_gate_other_endpoints() -> None:
    """Only POST /auth/login is guarded. /auth/register and GET /auth/login pass."""
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(),
        ) as verify_mock,
    ):
        register_res = client.post("/auth/register")
        get_login_res = client.get("/auth/login")
    assert register_res.status_code == 200
    assert get_login_res.status_code == 200
    verify_mock.assert_not_awaited()
