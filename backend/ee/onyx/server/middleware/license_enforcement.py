"""Middleware to enforce license status for SELF-HOSTED deployments only.

NOTE: This middleware is NOT used for multi-tenant (cloud) deployments.
Multi-tenant gating is handled separately by the control plane via the
/tenants/product-gating endpoint and is_tenant_gated() checks.

IMPORTANT: Mutual Exclusivity with ENTERPRISE_EDITION_ENABLED
============================================================
This middleware is controlled by LICENSE_ENFORCEMENT_ENABLED env var.
It works alongside the legacy ENTERPRISE_EDITION_ENABLED system:

- LICENSE_ENFORCEMENT_ENABLED=false (default):
  Middleware is disabled. EE features are controlled solely by
  ENTERPRISE_EDITION_ENABLED. This preserves legacy behavior.

- LICENSE_ENFORCEMENT_ENABLED=true:
  Middleware actively enforces license status. EE features require
  a valid license, regardless of ENTERPRISE_EDITION_ENABLED.

Eventually, ENTERPRISE_EDITION_ENABLED will be removed and license
enforcement will be the only mechanism for gating EE features.

License Enforcement States (when enabled)
=========================================
For self-hosted deployments:

1. No license (never subscribed):
   - Allow community features (basic connectors, search, chat)
   - Block EE-only features (analytics, user groups, etc.)

2. GATED_ACCESS (fully expired):
   - Block all routes except billing/auth/license
   - User must renew subscription to continue

3. Valid license (ACTIVE, GRACE_PERIOD, PAYMENT_REMINDER):
   - Full access to all EE features
   - Seat limits enforced
   - GRACE_PERIOD/PAYMENT_REMINDER are for notifications only, not blocking
"""

import logging
from collections.abc import Awaitable
from collections.abc import Callable

from fastapi import FastAPI
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.configs.license_enforcement_config import EE_ONLY_PATH_PREFIXES
from ee.onyx.configs.license_enforcement_config import (
    LICENSE_ENFORCEMENT_ALLOWED_PREFIXES,
)
from ee.onyx.db.license import get_cached_license_metadata
from ee.onyx.db.license import refresh_license_cache
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.settings.models import ApplicationStatus
from shared_configs.contextvars import get_current_tenant_id


def _is_path_allowed(path: str) -> bool:
    """Check if path is in allowlist (prefix match)."""
    return any(
        path.startswith(prefix) for prefix in LICENSE_ENFORCEMENT_ALLOWED_PREFIXES
    )


def _is_ee_only_path(path: str) -> bool:
    """Check if path requires EE license (prefix match)."""
    return any(path.startswith(prefix) for prefix in EE_ONLY_PATH_PREFIXES)


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
        tenant_id = get_current_tenant_id()

        try:
            metadata = get_cached_license_metadata(tenant_id)

            # If no cached metadata, check database (cache may have been cleared)
            if not metadata:
                logger.debug(
                    f"[license_enforcement] No cached license for tenant {tenant_id}, "
                    "checking database..."
                )
                try:
                    with get_session_with_current_tenant() as db_session:
                        metadata = refresh_license_cache(db_session, tenant_id)
                        if metadata:
                            logger.info(
                                f"[license_enforcement] Loaded license from DB for tenant {tenant_id}"
                            )
                except SQLAlchemyError as db_error:
                    logger.warning(
                        f"[license_enforcement] Failed to check database for license: {db_error}"
                    )

            if metadata:
                # User HAS a license (current or expired)
                if metadata.status == ApplicationStatus.GATED_ACCESS:
                    # License fully expired - gate the user
                    # Note: GRACE_PERIOD and PAYMENT_REMINDER are for notifications only,
                    # they don't block access
                    is_gated = True
                else:
                    # License is active - check seat limit
                    # used_seats in cache is kept accurate via invalidation
                    # when users are added/removed
                    if metadata.used_seats > metadata.seats:
                        logger.info(
                            f"Blocking request for tenant {tenant_id}: "
                            f"seat limit exceeded ({metadata.used_seats}/{metadata.seats})"
                        )
                        return JSONResponse(
                            status_code=402,
                            content={
                                "detail": {
                                    "error": "seat_limit_exceeded",
                                    "message": f"Seat limit exceeded: {metadata.used_seats} of {metadata.seats} seats used.",
                                    "used_seats": metadata.used_seats,
                                    "seats": metadata.seats,
                                }
                            },
                        )
            else:
                # No license in cache OR database = never subscribed
                # Allow community features, but block EE-only features
                if _is_ee_only_path(path):
                    logger.info(
                        f"[license_enforcement] Blocking EE-only path for unlicensed tenant {tenant_id}: {path}"
                    )
                    return JSONResponse(
                        status_code=402,
                        content={
                            "detail": {
                                "error": "enterprise_license_required",
                                "message": "This feature requires an Enterprise license. "
                                "Please upgrade to access this functionality.",
                            }
                        },
                    )
                logger.debug(
                    f"[license_enforcement] No license for tenant {tenant_id}, "
                    "allowing community features"
                )
                is_gated = False
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
