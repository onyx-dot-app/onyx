"""Mobile auth gateway.

Native mobile clients (Expo / React Native) authenticate against the SAME
backend as web, but receive the existing stateful session token as a Bearer
value instead of an HttpOnly cookie. This module owns the mobile-facing auth
surface.

Endpoints:
  - POST /auth/mobile/login         email/password -> {access_token, token_type}
  - POST /auth/mobile/logout        revoke the current session token
  - POST /auth/mobile/refresh       extend / reissue the session token
  - POST /auth/mobile/sso/exchange  swap a one-time SSO code (+ PKCE verifier)
                                    for the session token (Google SSO bridge)
"""

from fastapi import APIRouter
from pydantic import BaseModel

from onyx.auth.mobile_sso.code_store import consume_sso_code
from onyx.auth.users import fastapi_users
from onyx.auth.users import mobile_auth_backend
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

# Prefix ("/auth/mobile") is applied at registration in main.py. The bearer
# login/refresh/logout sub-routers are built from `mobile_auth_backend`, so they
# reuse the existing session strategy — the Bearer token is the exact same token
# web gets (server-revocable under the redis/postgres backends); only the
# transport differs. Their route names are namespaced `auth:mobile-bearer.*`, so
# they never collide with the web cookie backend's `auth:<backend>.*` routes.
router = APIRouter()
# get_auth_router provides both /login and /logout for the bearer backend.
router.include_router(fastapi_users.get_auth_router(mobile_auth_backend))
router.include_router(fastapi_users.get_refresh_router(mobile_auth_backend))


class MobileSsoExchangeRequest(BaseModel):
    code: str
    code_verifier: str


class MobileSsoTokenResponse(BaseModel):
    # Same shape as the bearer login/refresh responses so the client has one
    # token-handling path regardless of how it authenticated.
    access_token: str
    token_type: str = "bearer"


@router.post("/sso/exchange")
async def sso_exchange(payload: MobileSsoExchangeRequest) -> MobileSsoTokenResponse:
    """Swap a one-time SSO code (+ PKCE verifier) for the session token.

    Returns the same `{access_token, token_type}` shape as the bearer login. Any
    failure — unknown / expired / replayed code, or a verifier that doesn't match
    the stored PKCE challenge — yields one generic 401 with no oracle (see
    `consume_sso_code`).
    """
    token = await consume_sso_code(payload.code, payload.code_verifier)
    if token is None:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, "Invalid or expired code")
    return MobileSsoTokenResponse(access_token=token)
