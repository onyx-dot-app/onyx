"""Tenant-specific usage limit overrides from the control plane (EE version)."""

import time

import requests

from ee.onyx.server.tenants.access import generate_data_plane_token
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.configs.app_configs import DEV_MODE
from onyx.server.tenant_usage_limits import TenantUsageLimitOverrides
from onyx.server.usage_limits import NO_LIMIT
from onyx.utils.logger import setup_logger

logger = setup_logger()


# In-memory storage for tenant overrides (populated at startup)
_tenant_usage_limit_overrides: dict[str, TenantUsageLimitOverrides] | None = None
_last_fetch_time: float = 0.0
_FETCH_INTERVAL = 60 * 60 * 24  # 24 hours
_ERROR_FETCH_INTERVAL = 30 * 60  # 30 minutes (if the last fetch failed)


def fetch_usage_limit_overrides() -> dict[str, TenantUsageLimitOverrides] | None:
    """
    Fetch tenant-specific usage limit overrides from the control plane.

    Returns:
        Dictionary mapping tenant_id to their specific limit overrides.
        Returns empty dict on any error (falls back to defaults).
    """
    try:
        token = generate_data_plane_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{CONTROL_PLANE_API_BASE_URL}/usage-limit-overrides"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        tenant_overrides = response.json()

        # Parse each tenant's overrides
        result: dict[str, TenantUsageLimitOverrides] = {}
        for override_data in tenant_overrides:
            tenant_id = override_data["tenant_id"]
            try:
                result[tenant_id] = TenantUsageLimitOverrides(**override_data)
            except Exception as e:
                logger.warning(
                    f"Failed to parse usage limit overrides for tenant {tenant_id}: {e}"
                )

        return (
            result or None
        )  # if empty dictionary, something went wrong and we shouldn't enforce limits

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch usage limit overrides from control plane: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing usage limit overrides: {e}")
        return None


def load_usage_limit_overrides() -> None:
    """
    Load tenant usage limit overrides from the control plane.
    """
    global _tenant_usage_limit_overrides
    global _last_fetch_time

    logger.info("Loading tenant usage limit overrides from control plane...")
    overrides = fetch_usage_limit_overrides()

    _last_fetch_time = time.time()

    # use the new result if it exists, otherwise use the old result
    # (prevents us from updating to a failed fetch result)
    _tenant_usage_limit_overrides = overrides or _tenant_usage_limit_overrides

    if overrides:
        logger.info(f"Loaded usage limit overrides for {len(overrides)} tenants")
    else:
        logger.info("No tenant-specific usage limit overrides found")


def unlimited(tenant_id: str) -> TenantUsageLimitOverrides:
    return TenantUsageLimitOverrides(
        tenant_id=tenant_id,
        llm_cost_cents_trial=NO_LIMIT,
        llm_cost_cents_paid=NO_LIMIT,
        chunks_indexed_trial=NO_LIMIT,
        chunks_indexed_paid=NO_LIMIT,
        api_calls_trial=NO_LIMIT,
        api_calls_paid=NO_LIMIT,
        non_streaming_calls_trial=NO_LIMIT,
        non_streaming_calls_paid=NO_LIMIT,
    )


def get_tenant_usage_limit_overrides(
    tenant_id: str,
) -> TenantUsageLimitOverrides | None:
    """
    Get the usage limit overrides for a specific tenant.

    Args:
        tenant_id: The tenant ID to look up

    Returns:
        TenantUsageLimitOverrides if the tenant has overrides, None otherwise.
    """
    global _tenant_usage_limit_overrides
    time_since = time.time() - _last_fetch_time
    if (
        _tenant_usage_limit_overrides is None and time_since > _ERROR_FETCH_INTERVAL
    ) or (time_since > _FETCH_INTERVAL):
        logger.debug(
            f"Last fetch time: {_last_fetch_time}, time since last fetch: {time_since}"
        )

        load_usage_limit_overrides()

    # If we have failed to fetch from the control plane or we're in dev mode, don't usage limit anyone.
    if _tenant_usage_limit_overrides is None or DEV_MODE:
        return unlimited(tenant_id)
    return _tenant_usage_limit_overrides.get(tenant_id)
