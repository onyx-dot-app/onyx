"""Mobile auth gateway.

Native mobile clients (Expo / React Native) authenticate against the SAME
backend as web, but receive the existing stateful session token as a Bearer
value instead of an HttpOnly cookie. This module owns the mobile-facing auth
surface.

V1 (this PR): email/password login, refresh, and logout, mounted from the
shared fastapi-users machinery against the `mobile-bearer` backend. The Google
SSO bridge (`/auth/mobile/sso/exchange`) is added in a later PR.

See docs/mobile-auth/.
"""

from fastapi import APIRouter

from onyx.auth.users import fastapi_users
from onyx.auth.users import mobile_auth_backend


def get_mobile_auth_router() -> APIRouter:
    """Build the `/auth/mobile` router (prefix applied at registration).

    Exposes:
      - POST /auth/mobile/login   email/password -> {access_token, token_type}
      - POST /auth/mobile/logout  revoke the current session token
      - POST /auth/mobile/refresh extend / reissue the session token

    All three reuse the existing session strategy (so the Bearer token is the
    exact same revocable token web gets) — only the transport differs. Routes
    are namespaced `auth:mobile-bearer.*`, so they never collide with the web
    cookie backend's `auth:<backend>.*` routes.
    """
    router = APIRouter()
    # get_auth_router provides both /login and /logout for the bearer backend.
    router.include_router(fastapi_users.get_auth_router(mobile_auth_backend))
    router.include_router(fastapi_users.get_refresh_router(mobile_auth_backend))
    return router
