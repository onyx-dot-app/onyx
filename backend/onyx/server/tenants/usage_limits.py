"""
Non-EE version of tenant usage limit overrides.

In non-EE deployments, there are no tenant-specific overrides - all tenants
use the default limits from environment variables.

The EE version (ee.onyx.server.tenants.usage_limits) fetches per-tenant
overrides from the control plane.
"""

from pydantic import BaseModel


class TenantUsageLimitOverrides(BaseModel):
    """Usage limit overrides for a specific tenant.

    Field behavior:
    - Field not present or set to null: Use the default env var value
    - Field set to -1: No limit (unlimited)
    - Field set to a positive integer: Use that specific limit
    """

    llm_cost_cents_trial: int | None = None
    llm_cost_cents_paid: int | None = None
    chunks_indexed_trial: int | None = None
    chunks_indexed_paid: int | None = None
    api_calls_trial: int | None = None
    api_calls_paid: int | None = None
    non_streaming_calls_trial: int | None = None
    non_streaming_calls_paid: int | None = None


def get_tenant_usage_limit_overrides(
    tenant_id: str,
) -> TenantUsageLimitOverrides | None:
    """
    Get the usage limit overrides for a specific tenant.

    Non-EE version always returns None (no overrides available).
    The EE version fetches tenant-specific overrides from the control plane.

    Args:
        tenant_id: The tenant ID to look up

    Returns:
        None - no overrides in non-EE deployments
    """
    return None


def load_usage_limit_overrides() -> None:
    """
    Load tenant usage limit overrides from the control plane.

    Non-EE version is a no-op since there's no control plane to fetch from.
    """
