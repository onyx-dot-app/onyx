"""Middleware to enforce license status application-wide."""

import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.server.tenants.product_gating import is_tenant_gated
from onyx.server.settings.models import ApplicationStatus
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id


# Paths that are ALWAYS accessible, even when gated
ALLOWED_PATH_PREFIXES = {
    "/auth",  # Login/logout
    "/health",  # Health checks
    "/openapi.json",  # API docs
    "/license",  # License management (fetch, upload, status)
    "/tenants/billing",  # Billing management
    "/settings",  # Need to see status
    "/enterprise-settings",  # Need to see enterprise status/branding
    "/me",  # Basic user info
    "/metrics",  # Prometheus metrics
    "/docs",  # Swagger UI
    "/redoc",  # ReDoc
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
        # Feature flag check
        if not LICENSE_ENFORCEMENT_ENABLED:
            return await call_next(request)

        # Allow health checks and allowlisted paths
        path = request.url.path
        # Strip API prefix if present (e.g., /api/settings -> /settings)
        if path.startswith("/api"):
            path = path[4:]

        if _is_path_allowed(path):
            logger.debug(f"License enforcement: allowing {path} (allowlisted)")
            return await call_next(request)

        # Check license status
        is_gated = False
        tenant_id = get_current_tenant_id()

        if MULTI_TENANT:
            # Multi-tenant: check Redis gated tenants set
            try:
                is_gated = is_tenant_gated(tenant_id)
                logger.debug(
                    f"License enforcement: tenant={tenant_id}, is_gated={is_gated}"
                )
            except Exception as e:
                logger.warning(f"Failed to check tenant gating status: {e}")
                # Fail open - don't block on Redis errors
                is_gated = False
        else:
            # Self-hosted: check license metadata cache
            try:
                from ee.onyx.db.license import get_cached_license_metadata

                metadata = get_cached_license_metadata(tenant_id)
                if metadata:
                    logger.debug(
                        f"License enforcement: tenant={tenant_id}, "
                        f"status={metadata.status}, path={path}"
                    )
                    if metadata.status == ApplicationStatus.GATED_ACCESS:
                        is_gated = True
                else:
                    # No license = gated (can't bypass by deleting license)
                    logger.debug(
                        f"License enforcement: tenant={tenant_id}, "
                        f"no license found - blocking, path={path}"
                    )
                    is_gated = True
            except Exception as e:
                logger.warning(f"Failed to check license metadata: {e}")
                # Fail open - don't block on cache errors
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
