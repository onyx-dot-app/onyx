from onyx.configs.app_configs import HOOK_ENABLED
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from shared_configs.configs import MULTI_TENANT


def require_hook_enabled() -> None:
    """FastAPI dependency that gates all hook management endpoints.

    Hooks are only available in single-tenant / self-hosted deployments with
    HOOK_ENABLED=true explicitly set. Two layers of protection:
      1. MULTI_TENANT check — rejects even if HOOK_ENABLED is accidentally set true
      2. HOOK_ENABLED flag — explicit opt-in by the operator

    Use as: Depends(require_hook_enabled)
    """
    if MULTI_TENANT:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Custom code hooks are not available in multi-tenant deployments",
        )
    if not HOOK_ENABLED:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Custom code hooks are not enabled. Set HOOK_ENABLED=true to enable.",
        )
