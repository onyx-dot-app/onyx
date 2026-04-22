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


def test_health_check_bypass_allows_request() -> None:
    """Valid X-Healthcheck-Token header skips captcha verification entirely."""
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "HEALTH_CHECK_BYPASS_TOKEN",
            "super-secret-bypass-token",
        ),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(),
        ) as verify_mock,
    ):
        res = client.post(
            "/auth/login",
            headers={"X-Healthcheck-Token": "super-secret-bypass-token"},
        )
    assert res.status_code == 200
    assert res.json() == {"status": "logged-in"}
    verify_mock.assert_not_awaited()


def test_health_check_bypass_wrong_secret_falls_through_to_captcha() -> None:
    """Wrong secret in X-Healthcheck-Token must NOT bypass — normal captcha path runs."""
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "HEALTH_CHECK_BYPASS_TOKEN",
            "super-secret-bypass-token",
        ),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(
                side_effect=CaptchaVerificationError(
                    "Captcha verification failed: Captcha token is required"
                )
            ),
        ) as verify_mock,
    ):
        res = client.post(
            "/auth/login",
            headers={"X-Healthcheck-Token": "wrong-guess"},
        )
    assert res.status_code == 403
    verify_mock.assert_awaited_once_with("", CaptchaAction.LOGIN)


def test_health_check_bypass_disabled_when_env_empty_is_fail_closed() -> None:
    """Empty HEALTH_CHECK_BYPASS_TOKEN env var must never match any header value,
    regardless of whether the client header is empty or non-empty. Exercises
    both ``if not expected`` (server side) and ``if not provided`` (client side)
    early-return guards.
    """
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(captcha_api_module, "HEALTH_CHECK_BYPASS_TOKEN", ""),
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(
                side_effect=CaptchaVerificationError(
                    "Captcha verification failed: Captcha token is required"
                )
            ),
        ) as verify_mock,
    ):
        # Empty client header: hits `if not provided` guard.
        res_empty = client.post(
            "/auth/login",
            headers={"X-Healthcheck-Token": ""},
        )
        # Non-empty client header: exercises the `if not expected` guard
        # specifically — confirms an unset server secret never accidentally
        # matches an arbitrary client-supplied token.
        res_nonempty = client.post(
            "/auth/login",
            headers={"X-Healthcheck-Token": "attacker-guess-12345"},
        )
    assert res_empty.status_code == 403
    assert res_nonempty.status_code == 403
    assert verify_mock.await_count == 2
    assert verify_mock.await_args_list[0].args == ("", CaptchaAction.LOGIN)
    assert verify_mock.await_args_list[1].args == ("", CaptchaAction.LOGIN)


def test_health_check_bypass_uses_constant_time_compare() -> None:
    """Assert hmac.compare_digest is the comparison primitive (no `==` timing oracle)."""
    app = build_app()
    client = TestClient(app)
    with (
        patch.object(captcha_api_module, "is_captcha_enabled", return_value=True),
        patch.object(
            captcha_api_module,
            "HEALTH_CHECK_BYPASS_TOKEN",
            "super-secret-bypass-token",
        ),
        patch.object(
            captcha_api_module.hmac,
            "compare_digest",
            wraps=captcha_api_module.hmac.compare_digest,
        ) as compare_spy,
        patch.object(
            captcha_api_module,
            "verify_captcha_token",
            new=AsyncMock(),
        ),
    ):
        client.post(
            "/auth/login",
            headers={"X-Healthcheck-Token": "super-secret-bypass-token"},
        )
    compare_spy.assert_called_once_with(
        "super-secret-bypass-token", "super-secret-bypass-token"
    )
