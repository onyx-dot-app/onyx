import asyncio
import logging
import sys
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse

from ee.onyx.auth.users import decode_anonymous_user_jwt_token
from ee.onyx.configs.multi_tenant_gating_config import (
    MULTI_TENANT_GATING_ALLOWED_PREFIXES,
)
from ee.onyx.server.tenants.product_gating import is_tenant_gated
from onyx.auth.utils import extract_tenant_from_auth_header
from onyx.configs.constants import ANONYMOUS_USER_COOKIE_NAME
from onyx.configs.constants import TENANT_ID_COOKIE_NAME
from onyx.db.engine.sql_engine import is_valid_schema_name
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.redis.redis_pool import retrieve_auth_token_data_from_bearer
from onyx.redis.redis_pool import retrieve_auth_token_data_from_redis
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Unauthenticated, non-tenant-scoped endpoints (LB/Prometheus probes, API docs),
# so tenant resolution is skipped for them.
TENANT_RESOLUTION_SKIP_PATHS = frozenset({"/health", "/metrics", "/openapi.json"})


def add_api_server_tenant_id_middleware(
    app: FastAPI, logger: logging.LoggerAdapter
) -> None:
    @app.middleware("http")
    async def set_tenant_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Extracts the tenant id from multiple locations and sets the context var.

        This is very specific to the api server and probably not something you'd want
        to use elsewhere.
        """
        try:
            if request.url.path in TENANT_RESOLUTION_SKIP_PATHS:
                CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
                return await call_next(request)

            if MULTI_TENANT:
                tenant_id = await _get_tenant_id_from_request(request, logger)
            else:
                tenant_id = POSTGRES_DEFAULT_SCHEMA

            CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)

            # Block tenants whose subscription has lapsed (`application_status =
            # GATED_ACCESS` in the cloud control plane → `gated_tenants` Redis
            # set) from reaching anything outside the resubscribe surface. The
            # frontend ProductGatingWrapper only swaps UI; direct API callers
            # (bots with stored auth, PATs, scripts) used to walk past it and
            # keep burning the cloud LLM key. Skip the lookup for the default
            # schema (unauthenticated requests) — it is never in the gated set
            # and the round-trip is wasted. Allowlist is the cloud-only
            # `MULTI_TENANT_GATING_ALLOWED_PREFIXES` (auth, /me, /settings,
            # billing endpoints) — see that constant for the exact surface.
            if (
                MULTI_TENANT
                and tenant_id != POSTGRES_DEFAULT_SCHEMA
                and not _is_path_allowed(request.url.path)
            ):
                try:
                    # `is_tenant_gated` uses the sync Redis client; offload so
                    # the SISMEMBER round-trip does not block the event loop.
                    gated = await asyncio.to_thread(is_tenant_gated, tenant_id)
                except Exception:
                    # Fail open on Redis errors — don't lock paying tenants out
                    # because of cache connectivity issues.
                    logger.warning(
                        "[tenant_tracking] is_tenant_gated check failed; allowing request"
                    )
                    gated = False

                if gated:
                    logger.info(
                        "[tenant_tracking] Blocking gated tenant: tenant=%s path=%s",
                        tenant_id,
                        request.url.path,
                    )
                    code, status = OnyxErrorCode.SUBSCRIPTION_INACTIVE.value
                    return JSONResponse(
                        status_code=status,
                        content={
                            "error_code": code,
                            "detail": "Your subscription is inactive. Update your billing to restore access.",
                        },
                    )

            return await call_next(request)

        except Exception as e:
            logger.exception("Error in tenant ID middleware: %s", str(e))
            raise


def _is_path_allowed(path: str) -> bool:
    if path.startswith("/api/"):
        path = path[4:]
    return any(
        path.startswith(prefix) for prefix in MULTI_TENANT_GATING_ALLOWED_PREFIXES
    )


async def _get_tenant_id_from_request(
    request: Request, logger: logging.LoggerAdapter
) -> str:
    """
    Attempt to extract tenant_id from:
    1) The API key or PAT (Personal Access Token) header
    2) The Redis-based session token (Cookie: fastapiusersauth, or the
       Authorization: Bearer header used by mobile clients)
    3) The anonymous user cookie
    Fallback: POSTGRES_DEFAULT_SCHEMA
    """
    # Check for API key or PAT in Authorization header
    tenant_id = extract_tenant_from_auth_header(request)
    if tenant_id is not None:
        return tenant_id

    try:
        # Look up the session token data in Redis. Web clients send it as the
        # `fastapiusersauth` cookie; mobile clients send the same opaque token as
        # an Authorization: Bearer header and carry no cookie.
        token_data = await retrieve_auth_token_data_from_redis(request)
        if token_data is None:
            token_data = await retrieve_auth_token_data_from_bearer(request)

        if token_data:
            tenant_id_from_payload = token_data.get(
                "tenant_id", POSTGRES_DEFAULT_SCHEMA
            )

            tenant_id = (
                str(tenant_id_from_payload)
                if tenant_id_from_payload is not None
                else None
            )

            if tenant_id and not is_valid_schema_name(tenant_id):
                raise HTTPException(status_code=400, detail="Invalid tenant ID format")

        # Check for anonymous user cookie
        anonymous_user_cookie = request.cookies.get(ANONYMOUS_USER_COOKIE_NAME)
        if anonymous_user_cookie:
            try:
                anonymous_user_data = decode_anonymous_user_jwt_token(
                    anonymous_user_cookie
                )
                tenant_id = anonymous_user_data.get(
                    "tenant_id", POSTGRES_DEFAULT_SCHEMA
                )

                if not tenant_id or not is_valid_schema_name(tenant_id):
                    raise HTTPException(
                        status_code=400, detail="Invalid tenant ID format"
                    )

                return tenant_id

            except Exception as e:
                logger.error("Error decoding anonymous user cookie: %s", str(e))
                # Continue and attempt to authenticate

        logger.debug(
            "Token data not found or expired in Redis, defaulting to POSTGRES_DEFAULT_SCHEMA"
        )

        # Return POSTGRES_DEFAULT_SCHEMA, so non-authenticated requests are sent to the default schema
        # The CURRENT_TENANT_ID_CONTEXTVAR is initialized with POSTGRES_DEFAULT_SCHEMA,
        # so we maintain consistency by returning it here when no valid tenant is found.
        return POSTGRES_DEFAULT_SCHEMA

    except Exception as e:
        logger.error("Unexpected error in _get_tenant_id_from_request: %s", str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

    finally:
        # Don't `return` while an exception is propagating — it would swallow it
        # and fall back to the wrong tenant. Fall back only on the normal path.
        if sys.exc_info()[0] is None:
            if tenant_id:
                return tenant_id

            # As a final step, check for explicit tenant_id cookie
            tenant_id_cookie = request.cookies.get(TENANT_ID_COOKIE_NAME)
            if tenant_id_cookie and is_valid_schema_name(tenant_id_cookie):
                return tenant_id_cookie

            # If we've reached this point, return the default schema
            return POSTGRES_DEFAULT_SCHEMA
