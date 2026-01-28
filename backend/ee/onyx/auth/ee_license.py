"""EE License requirement dependency for FastAPI endpoints.

This module provides a dependency that enforces EE license requirements
at the endpoint level, providing defense in depth alongside the middleware.

Usage:
    @router.get("/analytics")
    def get_analytics(
        _: None = Depends(require_ee_license),
    ):
        ...

This ensures that even if the middleware is bypassed or disabled,
the endpoint itself will reject requests without a valid license.
"""

from fastapi import HTTPException

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import get_cached_license_metadata
from onyx.server.settings.models import ApplicationStatus
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Status that blocks access entirely
_BLOCKING_STATUS = ApplicationStatus.GATED_ACCESS


def require_ee_license() -> None:
    """FastAPI dependency that requires a valid EE license.

    Raises HTTPException 402 if:
    - LICENSE_ENFORCEMENT_ENABLED is true AND
    - User has no license OR license is in GATED_ACCESS status

    For multi-tenant (cloud), this check is skipped as gating is
    handled by the control plane via is_tenant_gated().

    This provides defense in depth - endpoints are protected even if
    the middleware is bypassed or disabled.
    """
    if not LICENSE_ENFORCEMENT_ENABLED:
        # License enforcement disabled - allow access (legacy behavior)
        return

    if MULTI_TENANT:
        # Cloud mode - gating handled by control plane
        return

    tenant_id = get_current_tenant_id()

    try:
        metadata = get_cached_license_metadata(tenant_id)

        if metadata is None:
            # No license - block EE features
            logger.info(
                f"[require_ee_license] Blocking EE endpoint for unlicensed tenant {tenant_id}"
            )
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "enterprise_license_required",
                    "message": "This feature requires an Enterprise license. "
                    "Please upgrade to access this functionality.",
                },
            )

        if metadata.status == _BLOCKING_STATUS:
            # License expired
            logger.info(
                f"[require_ee_license] Blocking EE endpoint for gated tenant {tenant_id}"
            )
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "license_expired",
                    "message": "Your subscription has expired. Please update your billing.",
                },
            )

        # Valid license - allow access
        return

    except HTTPException:
        raise
    except Exception as e:
        # Log but fail closed for security
        logger.warning(f"[require_ee_license] Error checking license: {e}")
        raise HTTPException(
            status_code=402,
            detail={
                "error": "license_check_failed",
                "message": "Unable to verify license status. Please try again.",
            },
        )
