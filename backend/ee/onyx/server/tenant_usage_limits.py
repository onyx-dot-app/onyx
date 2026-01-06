"""Tenant-specific usage limit overrides from the control plane (EE version)."""

import requests

from ee.onyx.server.tenants.access import generate_data_plane_token
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.server.tenant_usage_limits import TenantUsageLimitOverrides
from onyx.utils.logger import setup_logger

logger = setup_logger()


# In-memory storage for tenant overrides (populated at startup)
_tenant_usage_limit_overrides: dict[str, TenantUsageLimitOverrides] | None = None


def fetch_usage_limit_overrides() -> dict[str, TenantUsageLimitOverrides]:
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

        return result

    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to fetch usage limit overrides from control plane: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error parsing usage limit overrides: {e}")
        return {}


def load_usage_limit_overrides() -> dict[str, TenantUsageLimitOverrides]:
    """
    Load tenant usage limit overrides from the control plane.

    Called at server startup to populate the in-memory cache.
    """
    global _tenant_usage_limit_overrides

    logger.info("Loading tenant usage limit overrides from control plane...")
    overrides = fetch_usage_limit_overrides()
    _tenant_usage_limit_overrides = overrides

    if overrides:
        logger.info(f"Loaded usage limit overrides for {len(overrides)} tenants")
    else:
        logger.info("No tenant-specific usage limit overrides found")
    return overrides


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
    if _tenant_usage_limit_overrides is None:
        _tenant_usage_limit_overrides = load_usage_limit_overrides()
    return _tenant_usage_limit_overrides.get(tenant_id)
