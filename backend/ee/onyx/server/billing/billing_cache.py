"""Redis-backed cache for control-plane billing lookups.

Without this cache, every document batch processed by a large indexing run
fires a `/billing-information` request at the control plane (via
`_check_chunk_usage_limit` → `check_usage_and_raise` → `is_tenant_on_trial`
→ `fetch_billing_information`). One legitimately-indexing tenant can thus
single-handedly dominate control-plane load.

Granularity is per-tenant `BillingInformation | SubscriptionStatusResponse`;
``cached_is_tenant_on_trial`` derives the trial flag from the same cached
entry so the two views cannot drift.

Fallback order on every call:
  1. Redis hit  → return the cached payload.
  2. Redis miss → control-plane fetch, write through, return.
  3. Redis error (read or write) → log and fall through to an uncached
     control-plane fetch. Preserves availability when Redis blips.
"""

import json
from typing import Any

from pydantic import ValidationError
from redis.exceptions import RedisError

from ee.onyx.server.tenants.billing import fetch_billing_information
from ee.onyx.server.tenants.models import BillingInformation
from ee.onyx.server.tenants.models import SubscriptionStatusResponse
from onyx.configs.app_configs import BILLING_CACHE_TTL_SECONDS
from onyx.redis.redis_pool import get_shared_redis_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

BILLING_CACHE_KEY = "billing:info:{tenant_id}"

_TRIAL_STATUSES: frozenset[str] = frozenset({"trialing"})

# Discriminator used to round-trip the union return type through Redis without
# losing the BillingInformation vs SubscriptionStatusResponse distinction.
_TYPE_BILLING = "billing"
_TYPE_STATUS = "status"


def _cache_key(tenant_id: str) -> str:
    return BILLING_CACHE_KEY.format(tenant_id=tenant_id)


def _serialize(info: BillingInformation | SubscriptionStatusResponse) -> str:
    kind = _TYPE_BILLING if isinstance(info, BillingInformation) else _TYPE_STATUS
    envelope: dict[str, Any] = {
        "type": kind,
        "payload": info.model_dump(mode="json"),
    }
    return json.dumps(envelope)


def _deserialize(raw: bytes | str) -> BillingInformation | SubscriptionStatusResponse:
    envelope = json.loads(raw)
    if not isinstance(envelope, dict):
        raise ValueError("Billing cache envelope must be a JSON object.")

    kind = envelope.get("type")

    payload = envelope.get("payload")
    if payload is None:
        payload_dict: dict[str, Any] = {}
    elif isinstance(payload, dict):
        payload_dict = payload
    else:
        raise ValueError("Billing cache payload must be a JSON object.")

    if kind == _TYPE_BILLING:
        return BillingInformation(**payload_dict)
    if kind == _TYPE_STATUS:
        return SubscriptionStatusResponse(**payload_dict)
    raise ValueError(f"Unknown billing cache envelope type: {kind!r}")


def cached_fetch_billing_information(
    tenant_id: str,
) -> BillingInformation | SubscriptionStatusResponse:
    """Return billing info for a tenant, preferring the per-tenant Redis
    entry over a control-plane round-trip. Writes the entry on miss with
    ``BILLING_CACHE_TTL_SECONDS`` TTL.

    Cloud-only: there is no control-plane billing in single-tenant
    deployments, so callers must already be on the multi-tenant path. Fail
    loudly rather than silently open a Redis/control-plane connection that a
    Lite deployment may not have.
    """
    if not MULTI_TENANT:
        raise RuntimeError(
            "cached_fetch_billing_information is cloud-only; gate callers on MULTI_TENANT"
        )

    redis = get_shared_redis_client()
    key = _cache_key(tenant_id)

    try:
        raw = redis.get(key)
    except RedisError as e:
        logger.warning(
            "billing cache read failed for tenant %s, falling through to CP: %s",
            tenant_id,
            e,
        )
        return fetch_billing_information(tenant_id)

    if raw and isinstance(raw, (bytes, str)):
        try:
            return _deserialize(raw)
        except (json.JSONDecodeError, ValueError, ValidationError) as e:
            # Corrupt or schema-drifted entry — discard and refetch. Pydantic
            # ``ValidationError`` is NOT a subclass of ``ValueError`` in v2,
            # so it must be caught explicitly; otherwise a schema change to
            # ``BillingInformation`` leaves every subsequent read failing for
            # the full TTL without ever reaching the refetch/overwrite below.
            logger.warning(
                "billing cache entry for tenant %s unparseable, refetching: %s",
                tenant_id,
                e,
            )

    info = fetch_billing_information(tenant_id)

    try:
        redis.setex(key, BILLING_CACHE_TTL_SECONDS, _serialize(info))
    except RedisError as e:
        logger.warning("billing cache write failed for tenant %s: %s", tenant_id, e)

    return info


def cached_is_tenant_on_trial(tenant_id: str) -> bool:
    """Cached equivalent of the trial check. Derived from the same cache
    entry as ``cached_fetch_billing_information`` so the boolean and the
    full billing object cannot drift.
    """
    if not MULTI_TENANT:
        # No control-plane billing in single-tenant; trial limits don't apply.
        return False

    info = cached_fetch_billing_information(tenant_id)
    if isinstance(info, SubscriptionStatusResponse):
        # No subscription on record — treat as trial (matches legacy behaviour
        # in ``ee.onyx.server.usage_limits.is_tenant_on_trial``).
        return True
    return info.status in _TRIAL_STATUSES


def invalidate_billing_cache(tenant_id: str) -> None:
    """Drop the cached entry for one tenant. Safe to call even when no entry
    exists. Used by call sites that just mutated the tenant's subscription
    (e.g. admin panel → control plane) and want the next read to refresh.
    """
    if not MULTI_TENANT:
        return

    try:
        get_shared_redis_client().delete(_cache_key(tenant_id))
    except RedisError as e:
        logger.warning(
            "billing cache invalidate failed for tenant %s: %s", tenant_id, e
        )
