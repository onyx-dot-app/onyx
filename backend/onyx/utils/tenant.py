from shared_configs.configs import TENANT_ID_PREFIX


def get_tenant_id_short_string(tenant_id: str) -> str:
    """Gets a short string representation of a full tenant id.

    Args:
        tenant_id: The full tenant id.

    Returns:
        str: The first 8 characters of the tenant id after removing the prefix.
    """
    tenant_display = tenant_id.removeprefix(TENANT_ID_PREFIX)
    short_tenant = tenant_display[:8]
    return short_tenant
