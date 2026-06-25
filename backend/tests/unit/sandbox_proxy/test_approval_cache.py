from uuid import uuid4

import pytest

from onyx.cache.interface import CacheBackend
from onyx.cache.interface import CacheLock
from onyx.db.enums import ApprovalDecision
from onyx.sandbox_proxy.approval_cache import _wake_key
from onyx.sandbox_proxy.approval_cache import cache_session_grant_actions
from onyx.sandbox_proxy.approval_cache import cached_session_grants_cover
from onyx.sandbox_proxy.approval_cache import wait_for_wake


class _MemoryCache(CacheBackend):
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expirations: list[tuple[str, int]] = []
        self.blpop_result: tuple[bytes, bytes] | None = None
        self.blpop_calls: list[tuple[list[str], int]] = []

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def set(
        self,
        key: str,
        value: str | bytes | int | float,
        ex: int | None = None,
    ) -> None:
        self.values[key] = str(value).encode()
        if ex is not None:
            self.expire(key, ex)

    def expire(self, key: str, seconds: int) -> None:
        self.expirations.append((key, seconds))

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.values

    def ttl(self, key: str) -> int:  # noqa: ARG002
        raise NotImplementedError

    def lock(self, name: str, timeout: float | None = None) -> CacheLock:  # noqa: ARG002
        raise NotImplementedError

    def rpush(self, key: str, value: str | bytes) -> None:  # noqa: ARG002
        raise NotImplementedError

    def blpop(self, keys: list[str], timeout: int = 0) -> tuple[bytes, bytes] | None:
        self.blpop_calls.append((keys, timeout))
        return self.blpop_result


@pytest.mark.asyncio
async def test_wait_for_wake_uses_short_poll_timeout() -> None:
    cache = _MemoryCache()
    approval_id = uuid4()
    cache.blpop_result = (
        _wake_key(approval_id).encode(),
        ApprovalDecision.APPROVED.value.encode(),
    )

    decision = await wait_for_wake(approval_id, timeout_s=30, cache=cache)

    assert decision == ApprovalDecision.APPROVED
    assert cache.blpop_calls == [([_wake_key(approval_id)], 1)]


def test_cached_session_grants_cover_requires_every_action() -> None:
    cache = _MemoryCache()
    session_id = uuid4()
    approval_id = uuid4()
    external_app_id = 42

    assert not cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post"],
        cache=cache,
    )

    cache_session_grant_actions(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post"],
        source_approval_id=approval_id,
        cache=cache,
    )

    assert cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post"],
        cache=cache,
    )
    assert not cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id,
        action_types=["slack.chat.post", "slack.files.upload"],
        cache=cache,
    )
    assert not cached_session_grants_cover(
        session_id=session_id,
        external_app_id=external_app_id + 1,
        action_types=["slack.chat.post"],
        cache=cache,
    )
    assert cache.expirations
    assert all(seconds == 3600 for _key, seconds in cache.expirations)
