import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

import onyx.redis.redis_pool as redis_pool


class _FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def incr(self, key: str) -> None:
        self.calls.append(("incr", (key,)))

    def expire(self, key: str, ttl_seconds: int) -> None:
        self.calls.append(("expire", (key, ttl_seconds)))

    async def execute(self) -> list[int | bool]:
        return [1, True]


class _FakeRedis:
    def __init__(self) -> None:
        self.pipeline_instance = _FakePipeline()
        self.set_calls: list[tuple[str, str, int]] = []
        self.decr_calls: list[str] = []

    def pipeline(self) -> _FakePipeline:
        return self.pipeline_instance

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.set_calls.append((key, value, ex))

    async def decr(self, key: str) -> None:
        self.decr_calls.append(key)


@pytest.mark.asyncio
async def test_store_ws_token_includes_tenant_id_without_weakening_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        redis_pool, "get_async_redis_connection", AsyncMock(return_value=redis)
    )
    monkeypatch.setattr(redis_pool, "get_current_tenant_id", lambda: "tenant-a")

    await redis_pool.store_ws_token("ws-token", "user-7")

    assert redis.pipeline_instance.calls == [
        ("incr", ("ws_token_rate:user-7",)),
        ("expire", ("ws_token_rate:user-7", 60)),
    ]
    assert redis.decr_calls == []
    assert len(redis.set_calls) == 1

    key, value, ttl_seconds = redis.set_calls[0]
    assert key == "ws_token:ws-token"
    assert json.loads(value) == {"sub": "user-7", "tenant_id": "tenant-a"}
    assert ttl_seconds == redis_pool.WS_TOKEN_TTL_SECONDS
