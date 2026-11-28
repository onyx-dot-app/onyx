"""Cache of each playground tenant's trial start and limit overrides.

The control plane owns these values. The data plane keeps only this cache, so
nothing has to be cleaned up when a tenant is deleted. It works like the billing
cache (``ee.onyx.server.billing.billing_cache``):

1. Cache hit: use the cached value.
2. Cache miss: read the tenant from the control plane and cache it.
3. Cache error: read from the control plane without caching.

If the control plane cannot be read (it is down, or it does not have the
endpoint), an empty value is cached for 60 seconds instead of the usual hour.
During those 60 seconds:
- the tenant has no overrides, so each limit uses the normal playground amount;
- the tenant has no trial start, so its periods use the calendar week;
- checks read the cached empty value, so the control plane is asked at most
  once a minute per tenant, not on every request.

A sales raise is pushed by the control plane and written here at once, so it
does not wait for the cache to expire.
"""

import threading
from datetime import datetime

from cachetools import LRUCache
from pydantic import ValidationError

from ee.onyx.server.tenant_usage_limits import fetch_tenant_usage_limit_state
from ee.onyx.server.tenants.models import TenantUsageLimitState
from onyx.cache.factory import get_shared_cache_backend
from onyx.cache.interface import CACHE_TRANSIENT_ERRORS
from onyx.configs.app_configs import BILLING_CACHE_TTL_SECONDS
from onyx.db.usage import UsageType
from onyx.utils.logger import setup_logger

logger = setup_logger()

_CACHE_KEY = "usage_limits:{tenant_id}"
# How long an empty value is kept after the control plane could not be read.
_FETCH_FAILED_TTL_SECONDS = 60

# A trial start never changes after sign-up (an extension moves only the trial
# end), so each process keeps it after the first read. Adding usage after every
# model call then needs no cache read for it.
_trial_starts: LRUCache[str, datetime] = LRUCache(maxsize=10_000)
_trial_starts_lock = threading.Lock()


def _cache_key(tenant_id: str) -> str:
    return _CACHE_KEY.format(tenant_id=tenant_id)


def _fetch(tenant_id: str) -> tuple[TenantUsageLimitState, bool]:
    """Read the tenant from the control plane. Returns the value and whether the
    read worked. A failed read gives an empty value."""
    try:
        return fetch_tenant_usage_limit_state(tenant_id), True
    except Exception as e:
        logger.warning(
            "Could not read usage limits for tenant %s from the control plane: %s",
            tenant_id,
            e,
        )
        return TenantUsageLimitState(), False


def cached_tenant_usage_limit_state(tenant_id: str) -> TenantUsageLimitState:
    """The tenant's trial start and overrides, from the cache when possible."""
    cache = get_shared_cache_backend()
    key = _cache_key(tenant_id)

    try:
        raw = cache.get(key)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning(
            "Usage limit cache read failed for tenant %s, reading the control plane: %s",
            tenant_id,
            e,
        )
        return _fetch(tenant_id)[0]

    if raw:
        try:
            return TenantUsageLimitState.model_validate_json(raw)
        except (ValueError, ValidationError) as e:
            logger.warning(
                "Usage limit cache entry for tenant %s could not be read, refetching: %s",
                tenant_id,
                e,
            )

    state, fetched = _fetch(tenant_id)
    ttl = BILLING_CACHE_TTL_SECONDS if fetched else _FETCH_FAILED_TTL_SECONDS
    try:
        cache.set(key, state.model_dump_json(), ex=ttl)
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning("Usage limit cache write failed for tenant %s: %s", tenant_id, e)
    return state


def store_tenant_usage_limit_state(
    tenant_id: str, state: TenantUsageLimitState
) -> bool:
    """Write a value pushed by the control plane. Returns False if the write
    failed; the old value then stays until it expires."""
    try:
        get_shared_cache_backend().set(
            _cache_key(tenant_id),
            state.model_dump_json(),
            ex=BILLING_CACHE_TTL_SECONDS,
        )
    except CACHE_TRANSIENT_ERRORS as e:
        logger.warning("Usage limit cache write failed for tenant %s: %s", tenant_id, e)
        return False
    if state.trial_start is not None:
        with _trial_starts_lock:
            _trial_starts[tenant_id] = state.trial_start
    return True


def cached_tenant_trial_start(tenant_id: str) -> datetime | None:
    """When the tenant's trial started, or None if it is not known."""
    with _trial_starts_lock:
        known = _trial_starts.get(tenant_id)
    if known is not None:
        return known

    trial_start = cached_tenant_usage_limit_state(tenant_id).trial_start
    if trial_start is not None:
        with _trial_starts_lock:
            _trial_starts[tenant_id] = trial_start
    return trial_start


def cached_tenant_limit_override(tenant_id: str, usage_type: UsageType) -> int | None:
    """The tenant's override for one usage type, or None if it has none."""
    return cached_tenant_usage_limit_state(tenant_id).limits.get(usage_type)
