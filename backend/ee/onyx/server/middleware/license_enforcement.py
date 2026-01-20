"""Middleware to enforce license status application-wide."""

import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import get_cached_license_metadata
from ee.onyx.server.tenants.product_gating import is_tenant_gated
from onyx.server.settings.models import ApplicationStatus
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Paths that are ALWAYS accessible, even when license is expired/gated.
# These enable users to:
#   /auth - Log in/out (users can't fix billing if locked out of auth)
#   /license - Fetch, upload, or check license status
#   /health - Health checks for load balancers/orchestrators
#   /me - Basic user info needed for UI rendering
#   /settings, /enterprise-settings - View app status and branding
#   /tenants/billing-* - Manage subscription to resolve gating
ALLOWED_PATH_PREFIXES = {
    "/auth",
    "/license",
    "/health",
    "/me",
    "/settings",
    "/enterprise-settings",
    "/tenants/billing-information",
    "/tenants/create-customer-portal-session",
    "/tenants/create-subscription-session",
}


def _is_path_allowed(path: str) -> bool:
    """Check if path is in allowlist (prefix match)."""
    return any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


def add_license_enforcement_middleware(
    app: FastAPI, logger: logging.LoggerAdapter
) -> None:
    logger.info("License enforcement middleware registered")

    @app.middleware("http")
    async def enforce_license(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Block requests when license is expired/gated."""
        if not LICENSE_ENFORCEMENT_ENABLED:
            return await call_next(request)

        path = request.url.path
        if path.startswith("/api"):
            path = path[4:]

        if _is_path_allowed(path):
            return await call_next(request)

        is_gated = False
        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
        if tenant_id is None:
            # Tenant context not set yet - pass through
            # This can happen if this middleware runs before tenant identification
            return await call_next(request)

        if MULTI_TENANT:
            try:
                is_gated = is_tenant_gated(tenant_id)
            except RedisError as e:
                logger.warning(f"Failed to check tenant gating status: {e}")
                # Fail open - don't block users due to Redis connectivity issues
                is_gated = False
        else:
            try:
                metadata = get_cached_license_metadata(tenant_id)
                if metadata:
                    if metadata.status == ApplicationStatus.GATED_ACCESS:
                        is_gated = True
                else:
                    # No license metadata = gated for self-hosted EE
                    is_gated = True
            except RedisError as e:
                logger.warning(f"Failed to check license metadata: {e}")
                # Fail open - don't block users due to Redis connectivity issues
                is_gated = False

        if is_gated:
            logger.info(f"Blocking request for gated tenant: {tenant_id}, path={path}")
            return JSONResponse(
                status_code=402,
                content={
                    "detail": {
                        "error": "license_expired",
                        "message": "Your subscription has expired. Please update your billing.",
                    }
                },
            )

        return await call_next(request)
