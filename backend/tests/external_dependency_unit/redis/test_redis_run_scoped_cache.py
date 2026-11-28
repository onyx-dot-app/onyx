"""The Redis store of a listing run's shared values, against a real Redis."""

from collections.abc import Iterator
from typing import cast
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from onyx.redis import redis_run_scoped_cache
from onyx.redis.redis_pool import get_raw_redis_client, get_redis_client
from onyx.redis.redis_run_scoped_cache import RedisRunScopedCache
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


@pytest.fixture
def tenant_id() -> Iterator[str]:
    tenant = f"tenant_test_{uuid4().hex[:12]}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
    yield tenant
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    raw = get_raw_redis_client()
    for key in raw.scan_iter(match=f"{tenant}:*"):
        raw.delete(key)


def test_a_value_is_kept_for_its_run_under_the_tenant(tenant_id: str) -> None:
    cache = RedisRunScopedCache("run-a")
    cache.set("sharepoint_group_expansion:https://tenant/sites/a", "value", 120)

    assert (
        RedisRunScopedCache("run-a").get(
            "sharepoint_group_expansion:https://tenant/sites/a"
        )
        == "value"
    )
    assert (
        RedisRunScopedCache("run-b").get(
            "sharepoint_group_expansion:https://tenant/sites/a"
        )
        is None
    )
    keys = [
        key.decode() for key in get_raw_redis_client().scan_iter(match=f"{tenant_id}:*")
    ]
    assert len(keys) == 1
    assert keys[0].startswith(f"{tenant_id}:run_scoped_cache:run-a:")
    # The key holds no name or URL from the source.
    assert "sites" not in keys[0]
    assert 0 < cast(int, get_raw_redis_client().ttl(keys[0])) <= 120


class _Unreachable:
    def get(self, _key: str) -> bytes | None:
        raise RedisConnectionError("down")

    def set(self, *_args: object, **_kwargs: object) -> None:
        raise RedisConnectionError("down")


def test_an_unreachable_redis_keeps_nothing(
    tenant_id: str,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_run_scoped_cache, "get_redis_client", _Unreachable)
    cache = RedisRunScopedCache("run-a")

    cache.set("key", "value", 60)
    assert cache.get("key") is None
    assert get_redis_client().get("key") is None
