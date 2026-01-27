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
For self-hosted deployments, there are three states:

1. No license (never subscribed):
   - Allow community features (basic connectors, search, chat)
   - Block EE-only features (analytics, user groups, etc.)

2. Gated license (GATED_ACCESS, GRACE_PERIOD, PAYMENT_REMINDER):
   - Block all routes except billing/auth/license
   - User must renew subscription to continue

3. Valid license (ACTIVE):
   - Full access to all EE features
   - Seat limits enforced
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
from ee.onyx.db.license import get_cached_license_metadata
from ee.onyx.db.license import refresh_license_cache
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.settings.models import ApplicationStatus
from shared_configs.contextvars import get_current_tenant_id

# Paths that are ALWAYS accessible, even when license is expired/gated.
# These enable users to:
#   /auth - Log in/out (users can't fix billing if locked out of auth)
#   /license - Fetch, upload, or check license status
#   /health - Health checks for load balancers/orchestrators
#   /me - Basic user info needed for UI rendering
#   /settings, /enterprise-settings - View app status and branding
#   /tenants/billing-* - Manage subscription to resolve gating
#   /proxy - Self-hosted proxy endpoints (have own license-based auth)
ALLOWED_PATH_PREFIXES = {
    "/auth",
    "/license",
    "/health",
    "/me",
    "/settings",
    "/enterprise-settings",
    # Billing endpoints (unified API for both MT and self-hosted)
    "/billing",
    # Proxy endpoints for self-hosted billing (no tenant context)
    "/proxy",
    # Legacy tenant billing endpoints (kept for backwards compatibility)
    "/tenants/billing-information",
    "/tenants/create-customer-portal-session",
    "/tenants/create-subscription-session",
    # User management - needed to remove users when seat limit exceeded
    "/manage/users",
    "/manage/admin/users",
    "/manage/admin/valid-domains",
    "/manage/admin/deactivate-user",
    "/manage/admin/delete-user",
    "/users",
    # Notifications - needed for UI to load properly
    "/notifications",
}

# EE-only paths that require a valid license.
# Users without a license (community edition) cannot access these.
# These are blocked even when user has never subscribed (no license).
EE_ONLY_PATH_PREFIXES = {
    # User groups and access control
    "/manage/admin/user-group",
    # Analytics and reporting
    "/analytics",
    # Query history (admin chat session endpoints)
    "/admin/chat-sessions",
    "/admin/chat-session-history",
    "/admin/query-history",
    # Usage reporting/export
    "/admin/usage-report",
    # Standard answers (canned responses)
    "/manage/admin/standard-answer",
    # Token rate limits
    "/admin/token-rate-limits",
    # Evals
    "/evals",
}


def _is_path_allowed(path: str) -> bool:
    """Check if path is in allowlist (prefix match)."""
    return any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


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
                if metadata.status in {
                    ApplicationStatus.GATED_ACCESS,
                    ApplicationStatus.GRACE_PERIOD,
                    ApplicationStatus.PAYMENT_REMINDER,
                }:
                    # License expired or has billing issues - gate the user
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
                                "detail": f"Seat limit exceeded: {metadata.used_seats} of {metadata.seats} seats used."
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
                            "detail": "This feature requires an Enterprise license. "
                            "Please upgrade to access this functionality.",
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

            # Determine if this is "no license" vs "expired license"
            try:
                cached = get_cached_license_metadata(tenant_id)
                if cached and cached.status in {
                    ApplicationStatus.GATED_ACCESS,
                    ApplicationStatus.GRACE_PERIOD,
                    ApplicationStatus.PAYMENT_REMINDER,
                }:
                    message = (
                        "Your subscription has expired. Please update your billing."
                    )
                else:
                    message = "A valid license is required to access this feature."
            except RedisError:
                # Redis down - use generic message
                message = "A valid license is required to access this feature."

            return JSONResponse(
                status_code=402,
                content={"detail": message},
            )

        return await call_next(request)
