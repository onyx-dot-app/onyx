from ee.onyx.configs.app_configs import GATED_TENANTS_KEY
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import ONYX_CLOUD_TENANT_ID
from onyx.server.settings.models import ApplicationStatus
from onyx.server.settings.store import (
    load_settings,
    settings_write_lock,
    store_settings,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

# Bound for one read of the gated set. The cache API needs an explicit limit.
_MAX_GATED_TENANTS = 1_000_000


def update_tenant_gating(tenant_id: str, status: ApplicationStatus) -> None:
    cache = get_cache_backend(tenant_id=ONYX_CLOUD_TENANT_ID)

    # Maintain the GATED_ACCESS set
    if status == ApplicationStatus.GATED_ACCESS:
        cache.set_add(GATED_TENANTS_KEY, tenant_id)
    else:
        cache.set_remove(GATED_TENANTS_KEY, tenant_id)


def store_product_gating(tenant_id: str, application_status: ApplicationStatus) -> None:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        # Shares the settings write lock so a concurrent settings writer cannot
        # merge onto a stale snapshot and drop application_status.
        with settings_write_lock():
            settings = load_settings()
            settings.application_status = application_status
            store_settings(settings)

        # Store gated tenant information in the cache
        update_tenant_gating(tenant_id, application_status)
    except Exception:
        logger.exception("Failed to gate product")
        raise
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def overwrite_full_gated_set(tenant_ids: list[str]) -> None:
    get_cache_backend(tenant_id=ONYX_CLOUD_TENANT_ID).set_replace(
        GATED_TENANTS_KEY, tenant_ids
    )


def get_gated_tenants() -> set[str]:
    cache = get_cache_backend(tenant_id=ONYX_CLOUD_TENANT_ID, replica=True)
    gated_tenants_bytes = cache.set_members(GATED_TENANTS_KEY, limit=_MAX_GATED_TENANTS)
    if len(gated_tenants_bytes) == _MAX_GATED_TENANTS:
        logger.error(
            "The gated tenant set reached the read limit of %s; some gated "
            "tenants are missing from this read",
            _MAX_GATED_TENANTS,
        )
    return {tenant_id.decode("utf-8") for tenant_id in gated_tenants_bytes}


def is_tenant_gated(tenant_id: str) -> bool:
    """Fast O(1) check if tenant is in gated set (multi-tenant only)."""
    cache = get_cache_backend(tenant_id=ONYX_CLOUD_TENANT_ID, replica=True)
    return cache.set_contains(GATED_TENANTS_KEY, tenant_id)
