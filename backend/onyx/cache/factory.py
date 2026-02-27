from collections.abc import Callable

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheBackendType
from onyx.configs.app_configs import CACHE_BACKEND


def _build_redis_backend(tenant_id: str) -> CacheBackend:
    from onyx.cache.redis_backend import RedisCacheBackend
    from onyx.redis.redis_pool import redis_pool

    return RedisCacheBackend(redis_pool.get_client(tenant_id))


_BACKEND_BUILDERS: dict[CacheBackendType, Callable[[str], CacheBackend]] = {
    CacheBackendType.REDIS: _build_redis_backend,
    # CacheBackendType.POSTGRES will be added in a follow-up PR.
}


def get_cache_backend(*, tenant_id: str | None = None) -> CacheBackend:
    """Return a tenant-aware ``CacheBackend``.

    If *tenant_id* is ``None``, the current tenant is read from the
    thread-local context variable (same behaviour as ``get_redis_client``).
    """
    if tenant_id is None:
        from shared_configs.contextvars import get_current_tenant_id

        tenant_id = get_current_tenant_id()

    builder = _BACKEND_BUILDERS.get(CACHE_BACKEND)
    if builder is None:
        raise ValueError(
            f"Unsupported CACHE_BACKEND={CACHE_BACKEND!r}. "
            f"Supported values: {[t.value for t in CacheBackendType]}"
        )
    return builder(tenant_id)


def get_shared_cache_backend() -> CacheBackend:
    """Return a ``CacheBackend`` in the shared (cross-tenant) namespace."""
    from shared_configs.configs import DEFAULT_REDIS_PREFIX

    return get_cache_backend(tenant_id=DEFAULT_REDIS_PREFIX)
