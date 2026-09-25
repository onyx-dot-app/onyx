import math

import pytest

from onyx.cache import factory
from onyx.cache.interface import CacheBackendType
from onyx.cache.postgres_backend import PostgresCacheBackend


@pytest.mark.parametrize("timeout", [0, -1, math.inf, math.nan])
def test_invalid_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        factory.get_cache_backend(tenant_id="tenant", operation_timeout_s=timeout)


def test_submillisecond_timeout_does_not_disable_postgres_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(factory, "CACHE_BACKEND", CacheBackendType.POSTGRES)
    backend = factory.get_cache_backend(tenant_id="tenant", operation_timeout_s=0.0001)
    assert isinstance(backend, PostgresCacheBackend)
    assert backend._statement_timeout_ms == 1
    default = factory.get_cache_backend(tenant_id="tenant")
    assert isinstance(default, PostgresCacheBackend)
    assert default._statement_timeout_ms is None
