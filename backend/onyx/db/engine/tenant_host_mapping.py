"""Resolve which Postgres host index a tenant lives on.

Resolution order (for multi-tenant mode with >1 host):
  1. In-process LRU cache
  2. Redis  key ``tenant_host:{tenant_id}``
  3. Control-plane ``GET /tenants/{tenant_id}/created-at`` → compute from cutoffs

The mapping is effectively immutable (tenant creation time never changes), so
Redis entries are stored without a TTL.
"""

import bisect
from datetime import datetime
from datetime import timezone
from functools import lru_cache

import requests
from pydantic import BaseModel

from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.configs.app_configs import POSTGRES_HOST_CUTOFFS
from onyx.configs.app_configs import POSTGRES_HOSTS
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

REDIS_TENANT_HOST_KEY_PREFIX = "tenant_host:"

_PARSED_CUTOFFS: list[datetime] | None = None


def _get_parsed_cutoffs() -> list[datetime]:
    global _PARSED_CUTOFFS
    if _PARSED_CUTOFFS is None:
        _PARSED_CUTOFFS = [
            datetime.fromisoformat(c.replace("Z", "+00:00"))
            for c in POSTGRES_HOST_CUTOFFS
        ]
    return _PARSED_CUTOFFS


def compute_host_index(created_at: datetime) -> int:
    """Pure function: given a tenant's creation time, return its host index."""
    cutoffs = _get_parsed_cutoffs()
    if not cutoffs:
        return 0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return bisect.bisect_right(cutoffs, created_at)


class TenantCreatedAtResponse(BaseModel):
    tenant_id: str
    created_at: datetime


def _fetch_created_at_from_control_plane(tenant_id: str) -> datetime:
    from ee.onyx.server.tenants.access import generate_data_plane_token

    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.get(
        f"{CONTROL_PLANE_API_BASE_URL}/tenants/{tenant_id}/created-at",
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    parsed = TenantCreatedAtResponse(**response.json())
    return parsed.created_at


def _only_one_host() -> bool:
    return len(POSTGRES_HOSTS) <= 1


def set_tenant_host_in_redis(tenant_id: str, host_index: int) -> None:
    """Write the tenant→host mapping into Redis (no TTL — effectively permanent)."""
    from onyx.redis.redis_pool import get_raw_redis_client

    client = get_raw_redis_client()
    client.set(f"{REDIS_TENANT_HOST_KEY_PREFIX}{tenant_id}", str(host_index))


def get_host_index_from_redis(tenant_id: str) -> int | None:
    """Read the host index from Redis only.  Returns None on miss.

    Use this when the CP cannot be queried (e.g. the tenant hasn't been
    registered with the CP yet, as is the case for pre-provisioned pool
    tenants).
    """
    if not MULTI_TENANT or _only_one_host():
        return 0
    from onyx.redis.redis_pool import get_raw_redis_client

    raw = get_raw_redis_client().get(f"{REDIS_TENANT_HOST_KEY_PREFIX}{tenant_id}")
    if raw is not None:
        return int(raw)
    return None


def get_host_index_for_tenant(tenant_id: str) -> int:
    """Return the Postgres host index for *tenant_id*.

    Fast-path: if there's only one configured host, always returns 0.
    Otherwise checks the LRU cache, then Redis, then the control plane.
    """
    if not MULTI_TENANT or _only_one_host():
        return 0

    cached = _lru_get_host_index(tenant_id)
    if cached is not None:
        return cached

    host_index = _resolve_and_cache(tenant_id)
    return host_index


@lru_cache(maxsize=16384)
def _lru_get_host_index(tenant_id: str) -> int | None:
    """Check Redis; return None on miss so the caller falls through to CP."""
    from onyx.redis.redis_pool import get_raw_redis_client

    client = get_raw_redis_client()
    raw = client.get(f"{REDIS_TENANT_HOST_KEY_PREFIX}{tenant_id}")
    if raw is not None:
        return int(raw)
    return None


def _resolve_and_cache(tenant_id: str) -> int:
    """Call the control plane, compute the host index, cache everywhere."""
    created_at = _fetch_created_at_from_control_plane(tenant_id)
    host_index = compute_host_index(created_at)

    set_tenant_host_in_redis(tenant_id, host_index)

    # Evict the sentinel None from the LRU so the next call hits the fresh value
    _lru_get_host_index.cache_clear()

    logger.info(
        f"Resolved tenant {tenant_id} → host {host_index} "
        f"(created_at={created_at.isoformat()})"
    )
    return host_index


def warm_tenant_host_cache(tenant_ids_by_host: dict[int, list[str]]) -> int:
    """Bulk-populate Redis with tenant→host mappings.

    Returns the total number of keys written.
    """
    from onyx.redis.redis_pool import get_raw_redis_client

    client = get_raw_redis_client()
    pipe = client.pipeline(transaction=False)
    count = 0
    for host_index, tenant_ids in tenant_ids_by_host.items():
        for tid in tenant_ids:
            pipe.set(f"{REDIS_TENANT_HOST_KEY_PREFIX}{tid}", str(host_index))
            count += 1
    pipe.execute()
    logger.info(f"Warmed {count} tenant→host Redis entries")
    return count
