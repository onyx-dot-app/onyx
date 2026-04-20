"""API + middleware for Cloudflare Turnstile enforcement on signup."""

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse

from onyx.auth.turnstile import issue_turnstile_cookie_value
from onyx.auth.turnstile import TURNSTILE_COOKIE_NAME
from onyx.auth.turnstile import turnstile_enforcement_enabled
from onyx.auth.turnstile import validate_turnstile_cookie_value
from onyx.auth.turnstile import verify_turnstile_token
from onyx.configs.app_configs import TURNSTILE_COOKIE_TTL_SECONDS
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/auth/turnstile", tags=PUBLIC_API_TAGS)


# Paths the middleware should challenge. Full paths as seen by the backend
# (after the cloud nginx strips the /api prefix).
GUARDED_SIGNUP_PATHS = frozenset(
    {
        "/auth/register",
        "/auth/oauth/callback",
    }
)


class TurnstileVerifyRequest(BaseModel):
    token: str


class TurnstileVerifyResponse(BaseModel):
    ok: bool


@router.post("/verify")
async def verify_turnstile(
    body: TurnstileVerifyRequest,
    request: Request,
    response: Response,
) -> TurnstileVerifyResponse:
    """Verify a Turnstile token and set a signed cookie on success.

    The cookie is sent automatically by the browser on subsequent signup
    requests (including the Google OAuth callback redirect, which we cannot
    otherwise attach a header to).
    """
    if not turnstile_enforcement_enabled():
        # Enforcement is off — nothing to do. Return ok so the frontend
        # doesn't block on a no-op deployment.
        return TurnstileVerifyResponse(ok=True)

    remote_ip = request.client.host if request.client else None
    success, error = await verify_turnstile_token(body.token, remote_ip)
    if not success:
        raise HTTPException(
            status_code=403,
            detail=f"Turnstile verification failed: {error or 'unknown'}",
        )

    response.set_cookie(
        key=TURNSTILE_COOKIE_NAME,
        value=issue_turnstile_cookie_value(),
        max_age=TURNSTILE_COOKIE_TTL_SECONDS,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return TurnstileVerifyResponse(ok=True)


class TurnstileMiddleware(BaseHTTPMiddleware):
    """Reject signup requests that don't carry a valid Turnstile cookie.

    Only enforces when ``turnstile_enforcement_enabled()`` returns true, so
    self-hosted, dev, and deployments without a secret key pass through
    transparently.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in GUARDED_SIGNUP_PATHS and turnstile_enforcement_enabled():
            cookie_value = request.cookies.get(TURNSTILE_COOKIE_NAME)
            if not validate_turnstile_cookie_value(cookie_value):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Turnstile challenge required. Refresh the page and try again."
                    },
                )
        return await call_next(request)
