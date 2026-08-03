"""Middleware to enforce license status for SELF-HOSTED deployments only.

NOTE: This middleware is NOT used for multi-tenant (cloud) deployments.
Multi-tenant gating is handled separately by the control plane via the
/tenants/product-gating endpoint and is_tenant_gated() checks.

Scope (post tier-split)
=======================
Per-feature gating (which paths require which tier) lives in the
`tier_gate` middleware and the `PATH_PREFIX_MIN_TIER` map. This
middleware only handles the orthogonal *license-state* concerns:

  - GATED_ACCESS (fully expired) → block everything except the
    billing / auth allowlist.
  - Seat-limit-exceeded → return 402 with a structured payload so
    the FE can render the "remove users" prompt.

Per-tier feature gating is `tier_gate`'s job, regardless of deployment.

IMPORTANT: Mutual Exclusivity with ENTERPRISE_EDITION_ENABLED
============================================================
This middleware is controlled by LICENSE_ENFORCEMENT_ENABLED env var.
It works alongside the legacy ENTERPRISE_EDITION_ENABLED system:

- LICENSE_ENFORCEMENT_ENABLED=false (default):
  Middleware is disabled. EE features are controlled solely by
  ENTERPRISE_EDITION_ENABLED. This preserves legacy behavior.

- LICENSE_ENFORCEMENT_ENABLED=true:
  Middleware actively enforces license state. EE features require
  a valid license, regardless of ENTERPRISE_EDITION_ENABLED.

Eventually, ENTERPRISE_EDITION_ENABLED will be removed and license
enforcement will be the only mechanism for gating EE features.

License Enforcement States (when enabled)
=========================================
For self-hosted deployments:

1. No license (never subscribed):
   - Allow community features (basic connectors, search, chat).
   - Per-feature gating (Business/Enterprise paths) is delegated to
     `tier_gate` — see PATH_PREFIX_MIN_TIER. This middleware no
     longer blocks EE-only paths directly.

2. GATED_ACCESS (fully expired):
   - Block all routes except billing/auth/license.
   - User must renew subscription to continue.

3. Valid license (ACTIVE, GRACE_PERIOD, PAYMENT_REMINDER):
   - Full access to all EE features (subject to tier_gate).
   - Seat limits enforced.
   - GRACE_PERIOD / PAYMENT_REMINDER are for notifications only, not
     blocking.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.configs.license_enforcement_config import (
    LICENSE_ENFORCEMENT_ALLOWED_PREFIXES,
)
from ee.onyx.db.license import get_cached_license_metadata, refresh_license_cache
from ee.onyx.server.license.models import LicenseMetadata
from ee.onyx.utils.license import maybe_schedule_license_reclaim
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.settings.models import ApplicationStatus
from shared_configs.contextvars import get_current_tenant_id


def _is_path_allowed(path: str) -> bool:
    """Check if path is in allowlist (prefix match)."""
    return any(
        path.startswith(prefix) for prefix in LICENSE_ENFORCEMENT_ALLOWED_PREFIXES
    )


# Caps the gated re-check at one DB re-check per worker per interval, since every
# request to a genuinely gated instance takes that branch, pre-auth.
_GATED_RECHECK_INTERVAL_SEC = 30.0
_last_gated_recheck = 0.0


def _refresh_from_db(tenant_id: str) -> LicenseMetadata | None:
    with get_session_with_current_tenant() as db_session:
        return refresh_license_cache(db_session, tenant_id)


def _should_recheck_gated() -> bool:
    global _last_gated_recheck
    now = time.monotonic()
    if now - _last_gated_recheck < _GATED_RECHECK_INTERVAL_SEC:
        return False
    _last_gated_recheck = now
    return True


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
        if path.startswith("/api/"):
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
                    "[license_enforcement] No cached license, checking database..."
                )
                try:
                    with get_session_with_current_tenant() as db_session:
                        metadata = refresh_license_cache(db_session, tenant_id)
                        if metadata:
                            logger.info(
                                "[license_enforcement] Loaded license from database"
                            )
                except SQLAlchemyError as db_error:
                    logger.warning(
                        "[license_enforcement] Failed to check database for license: %s",
                        db_error,
                    )

            if metadata:
                # Runs before any gating decision so a gated instance heals.
                # Off the event loop: it does Redis and broker I/O with no
                # socket timeout, and this middleware is async.
                await run_in_threadpool(
                    maybe_schedule_license_reclaim, metadata.expires_at, tenant_id
                )

                # User HAS a license (current or expired)
                if (
                    metadata.status == ApplicationStatus.GATED_ACCESS
                    and _should_recheck_gated()
                ):
                    # Re-read the row before gating: a renewal whose cache
                    # write failed must not stay gated for the entry's TTL.
                    try:
                        refreshed = await run_in_threadpool(_refresh_from_db, tenant_id)
                        if refreshed:
                            metadata = refreshed
                    except Exception as e:
                        # Best-effort: any failure keeps the cached verdict.
                        logger.warning(
                            "[license_enforcement] Gated re-check failed: %s", e
                        )

                if metadata.status == ApplicationStatus.GATED_ACCESS:
                    # GRACE_PERIOD and PAYMENT_REMINDER are notification-only,
                    # they don't block.
                    is_gated = True
                else:
                    # License is active - check seat limit
                    # used_seats in cache is kept accurate via invalidation
                    # when users are added/removed
                    if metadata.used_seats > metadata.seats:
                        logger.info(
                            "[license_enforcement] Blocking request: seat limit exceeded (%s/%s)",
                            metadata.used_seats,
                            metadata.seats,
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
                # No license in cache OR database = never subscribed.
                # Per-feature gating (which paths require Business / Enterprise)
                # is the responsibility of the tier_gate middleware. Here we
                # just keep the request flowing — community-tier paths remain
                # accessible.
                logger.debug(
                    "[license_enforcement] No license, deferring per-feature "
                    "gating to tier_gate middleware"
                )
                is_gated = False
        except CACHE_TRANSIENT_ERRORS as e:
            logger.warning("Failed to check license metadata: %s", e)
            # Fail open - don't block users due to cache connectivity issues
            is_gated = False

        if is_gated:
            logger.info(
                "[license_enforcement] Blocking request (license expired): %s", path
            )

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
