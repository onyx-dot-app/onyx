"""API + middleware for the reCAPTCHA cookie and header flows.

Three entry points are gated:

1. ``/auth/oauth/callback`` — the frontend pre-verifies a token and gets
   a signed HttpOnly cookie (``/auth/captcha/oauth-verify``) that rides
   along on the Google redirect, where ``CaptchaCookieMiddleware``
   checks it.
2. ``/auth/login`` — ``LoginCaptchaMiddleware`` verifies an
   ``X-Captcha-Token`` header before the fastapi-users handler runs.
3. ``/auth/register`` — captcha is enforced inside
   ``UserManager.create`` via the body's ``captcha_token`` field.
"""

import hmac

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from onyx.auth.captcha import (
    CAPTCHA_COOKIE_NAME,
    CaptchaAction,
    CaptchaVerificationError,
    is_captcha_enabled,
    issue_captcha_cookie_value,
    validate_captcha_cookie_value,
    verify_captcha_token,
)
from onyx.configs.app_configs import (
    CAPTCHA_COOKIE_TTL_SECONDS,
    HEALTH_CHECK_BYPASS_TOKEN,
)
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, onyx_error_to_json_response
from onyx.utils.client_ip import get_client_ip
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/auth/captcha", tags=PUBLIC_API_TAGS)


# Only the OAuth callback is gated here. /auth/register has its own
# captcha enforcement inside UserManager.create via the body's
# captcha_token field — the cookie layer is specifically for the OAuth
# redirect that our frontend cannot attach a header to.
GUARDED_OAUTH_CALLBACK_PATHS = frozenset({"/auth/oauth/callback"})


class OAuthCaptchaVerifyRequest(BaseModel):
    token: str


class OAuthCaptchaVerifyResponse(BaseModel):
    ok: bool


@router.post("/oauth-verify")
async def verify_oauth_captcha(
    body: OAuthCaptchaVerifyRequest,
    response: Response,
) -> OAuthCaptchaVerifyResponse:
    """Verify a reCAPTCHA token and set the OAuth-redirect cookie.

    If captcha enforcement is off the endpoint is a no-op so the frontend
    doesn't block on dormant deployments.
    """
    if not is_captcha_enabled():
        return OAuthCaptchaVerifyResponse(ok=True)

    try:
        await verify_captcha_token(body.token, CaptchaAction.OAUTH)
    except CaptchaVerificationError as exc:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, str(exc))

    response.set_cookie(
        key=CAPTCHA_COOKIE_NAME,
        value=issue_captcha_cookie_value(),
        max_age=CAPTCHA_COOKIE_TTL_SECONDS,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return OAuthCaptchaVerifyResponse(ok=True)


class CaptchaCookieMiddleware:
    """Reject OAuth-callback requests that don't carry a valid captcha cookie.

    No-op when ``is_captcha_enabled()`` is false so self-hosted and dev
    deployments pass through transparently.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        # Skip OPTIONS so CORS preflight is never blocked.
        is_guarded_callback = (
            request.method != "OPTIONS"
            and request.url.path in GUARDED_OAUTH_CALLBACK_PATHS
            and is_captcha_enabled()
        )
        if is_guarded_callback:
            cookie_value = request.cookies.get(CAPTCHA_COOKIE_NAME)
            if not validate_captcha_cookie_value(cookie_value):
                response = onyx_error_to_json_response(
                    OnyxError(
                        OnyxErrorCode.UNAUTHORIZED,
                        "Captcha challenge required. Refresh the page and try again.",
                    )
                )
                await response(scope, receive, send)
                return

        if not is_guarded_callback:
            await self.app(scope, receive, send)
            return

        # Clear the challenge cookie without replacing the streamed body.
        cookie_response = Response()
        cookie_response.delete_cookie(CAPTCHA_COOKIE_NAME, path="/")

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(
                    "set-cookie", cookie_response.headers["set-cookie"]
                )
            await send(message)

        await self.app(scope, receive, send_with_cookie)


GUARDED_LOGIN_PATHS = frozenset({"/auth/login"})
LOGIN_CAPTCHA_HEADER = "X-Captcha-Token"
HEALTH_CHECK_BYPASS_HEADER = "X-Healthcheck-Token"


def _health_check_bypass_ok(request: Request) -> bool:
    """Constant-time compare of the request's health-check header against the
    server-side shared secret. Empty env var = bypass disabled (fail-closed)
    so an accidentally-unset secret never matches a blank client header.
    """
    expected = HEALTH_CHECK_BYPASS_TOKEN
    if not expected:
        return False
    provided = request.headers.get(HEALTH_CHECK_BYPASS_HEADER, "")
    if not provided:
        return False
    return hmac.compare_digest(expected, provided)


def _client_ip_for_log(request: Request) -> str:
    """Return the external client IP for log attribution. Delegates to the
    shared ``get_client_ip`` helper, which walks ``X-Forwarded-For``
    right-to-left and ignores spoofed left-side entries. Falls back to
    ``"unknown"`` so the log line never drops its ``client=`` field.
    """
    return get_client_ip(request) or "unknown"


class LoginCaptchaMiddleware:
    """Reject ``/auth/login`` requests without a valid captcha token.

    Enforced before the fastapi-users handler runs, so credential-stuffing
    attempts cost the attacker a fresh captcha token per try. No-op when
    ``is_captcha_enabled()`` is false.

    Automated health-check clients that present a valid
    ``X-Healthcheck-Token`` header skip the captcha step — the token is a
    backend-only shared secret, so possession alone does not grant auth
    (credentials are still required by the login handler).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        if (
            request.method == "POST"
            and request.url.path in GUARDED_LOGIN_PATHS
            and is_captcha_enabled()
        ):
            if _health_check_bypass_ok(request):
                logger.info(
                    "Login captcha bypassed via health-check token client=%s",
                    _client_ip_for_log(request),
                )
            else:
                token = request.headers.get(LOGIN_CAPTCHA_HEADER, "")
                try:
                    await verify_captcha_token(token, CaptchaAction.LOGIN)
                except CaptchaVerificationError as exc:
                    response = onyx_error_to_json_response(
                        OnyxError(OnyxErrorCode.UNAUTHORIZED, str(exc))
                    )
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)
