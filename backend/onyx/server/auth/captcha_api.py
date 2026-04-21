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

from fastapi import APIRouter
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from onyx.auth.captcha import CAPTCHA_COOKIE_NAME
from onyx.auth.captcha import CaptchaAction
from onyx.auth.captcha import CaptchaVerificationError
from onyx.auth.captcha import is_captcha_enabled
from onyx.auth.captcha import issue_captcha_cookie_value
from onyx.auth.captcha import validate_captcha_cookie_value
from onyx.auth.captcha import verify_captcha_token
from onyx.configs.app_configs import CAPTCHA_COOKIE_TTL_SECONDS
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import onyx_error_to_json_response
from onyx.error_handling.exceptions import OnyxError
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


class CaptchaCookieMiddleware(BaseHTTPMiddleware):
    """Reject OAuth-callback requests that don't carry a valid captcha cookie.

    No-op when ``is_captcha_enabled()`` is false so self-hosted and dev
    deployments pass through transparently.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip OPTIONS so CORS preflight is never blocked.
        is_guarded_callback = (
            request.method != "OPTIONS"
            and request.url.path in GUARDED_OAUTH_CALLBACK_PATHS
            and is_captcha_enabled()
        )
        if is_guarded_callback:
            cookie_value = request.cookies.get(CAPTCHA_COOKIE_NAME)
            if not validate_captcha_cookie_value(cookie_value):
                return onyx_error_to_json_response(
                    OnyxError(
                        OnyxErrorCode.UNAUTHORIZED,
                        "Captcha challenge required. Refresh the page and try again.",
                    )
                )

        response = await call_next(request)

        # One-time-use cookie: after the OAuth callback has been served, clear
        # it so the remaining TTL cannot be replayed (e.g. via browser
        # back-button) to re-enter the callback without a fresh challenge.
        if is_guarded_callback:
            response.delete_cookie(CAPTCHA_COOKIE_NAME, path="/")
        return response


GUARDED_LOGIN_PATHS = frozenset({"/auth/login"})
LOGIN_CAPTCHA_HEADER = "X-Captcha-Token"


class LoginCaptchaMiddleware(BaseHTTPMiddleware):
    """Reject ``/auth/login`` requests without a valid captcha token.

    Enforced before the fastapi-users handler runs, so credential-stuffing
    attempts cost the attacker a fresh captcha token per try. No-op when
    ``is_captcha_enabled()`` is false.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if (
            request.method == "POST"
            and request.url.path in GUARDED_LOGIN_PATHS
            and is_captcha_enabled()
        ):
            token = request.headers.get(LOGIN_CAPTCHA_HEADER, "")
            try:
                await verify_captcha_token(token, CaptchaAction.LOGIN)
            except CaptchaVerificationError as exc:
                return onyx_error_to_json_response(
                    OnyxError(OnyxErrorCode.UNAUTHORIZED, str(exc))
                )

        return await call_next(request)
