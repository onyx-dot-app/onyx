import math
from collections.abc import Callable

from onyx.cache.interface import CacheBackend, CacheBackendType
from onyx.configs.app_configs import CACHE_BACKEND


def _build_redis_backend(
    tenant_id: str, operation_timeout_s: float | None
) -> CacheBackend:
    from onyx.cache.redis_backend import RedisCacheBackend
    from onyx.redis.redis_pool import redis_pool

    return RedisCacheBackend(
        redis_pool.get_client(tenant_id, operation_timeout_s=operation_timeout_s)
    )


def _build_postgres_backend(
    tenant_id: str, operation_timeout_s: float | None
) -> CacheBackend:
    from onyx.cache.postgres_backend import PostgresCacheBackend

    return PostgresCacheBackend(
        tenant_id,
        statement_timeout_ms=(
            math.ceil(operation_timeout_s * 1000)
            if operation_timeout_s is not None
            else None
        ),
    )


_BACKEND_BUILDERS: dict[
    CacheBackendType, Callable[[str, float | None], CacheBackend]
] = {
    CacheBackendType.REDIS: _build_redis_backend,
    CacheBackendType.POSTGRES: _build_postgres_backend,
}


def get_cache_backend(
    *, tenant_id: str | None = None, operation_timeout_s: float | None = None
) -> CacheBackend:
    """Return a tenant-aware ``CacheBackend``.

    If *tenant_id* is ``None``, the current tenant is read from the
    thread-local context variable (same behaviour as ``get_redis_client``).
    An explicit timeout limits Redis I/O and pool waits where supported, or
    PostgreSQL statements and lock waits. None preserves backend defaults.
    This is not a total deadline; PostgreSQL connection acquisition is not covered.
    """
    if operation_timeout_s is not None and (
        not math.isfinite(operation_timeout_s) or operation_timeout_s <= 0
    ):
        raise ValueError("operation_timeout_s must be finite and positive")
    if tenant_id is None:
        from shared_configs.contextvars import get_current_tenant_id

        tenant_id = get_current_tenant_id()

    builder = _BACKEND_BUILDERS.get(CACHE_BACKEND)
    if builder is None:
        raise ValueError(
            f"Unsupported CACHE_BACKEND={CACHE_BACKEND!r}. Supported values: {[t.value for t in CacheBackendType]}"
        )
    return builder(tenant_id, operation_timeout_s)


def get_shared_cache_backend() -> CacheBackend:
    """Return a ``CacheBackend`` in the shared (cross-tenant) namespace."""
    from shared_configs.configs import DEFAULT_REDIS_PREFIX

    return get_cache_backend(tenant_id=DEFAULT_REDIS_PREFIX)
