from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

import onyx.redis.redis_pool as redis_pool
from onyx.voice.interface import VoiceSessionPolicy

POLICY = VoiceSessionPolicy(
    scope="acme",
    max_session_seconds=600,
    teardown_seconds=10,
    tenant_concurrency_limit=2,
    user_concurrency_limit=1,
    limit_message="Acme session limit reached.",
    timeout_message="Acme session timed out.",
)
TENANT_KEY = "voice_sessions:acme:tenant:tenant-a"
USER_KEY = f"{TENANT_KEY}:user:user-7"


class _Uuid:
    hex = "session-member-1"


class _FakeRedis:
    """Sorted sets keyed by name, plus the lock and expiry calls the guard uses."""

    def __init__(self) -> None:
        self.sets: dict[str, dict[str, float]] = {}
        self.expires: dict[str, int] = {}
        self.locks: list[dict[str, Any]] = []
        self.lock_held = False
        self.executed_batches: list[int] = []

    def lock(self, name: str, **kwargs: Any) -> Any:
        self.locks.append({"name": name, **kwargs})

        @asynccontextmanager
        async def _lock() -> Any:
            self.lock_held = True
            try:
                yield
            finally:
                self.lock_held = False

        return _lock()

    async def zremrangebyscore(self, key: str, _min: str, max_score: float) -> int:
        members = self.sets.get(key, {})
        expired = [m for m, score in members.items() if score <= max_score]
        for m in expired:
            del members[m]
        return len(expired)

    async def zcard(self, key: str) -> int:
        assert self.lock_held, "counts must happen under the admission lock"
        return len(self.sets.get(key, {}))

    def pipeline(self, transaction: bool) -> "_FakePipeline":
        assert transaction, "reservation writes must run in MULTI/EXEC"
        return _FakePipeline(self)

    def _zadd(self, key: str, mapping: dict[str, float]) -> None:
        assert self.lock_held, "adds must happen under the admission lock"
        self.sets.setdefault(key, {}).update(mapping)

    def _expire(self, key: str, seconds: int) -> None:
        self.expires[key] = seconds

    async def zrem(self, key: str, member: str) -> int:
        return 1 if self.sets.get(key, {}).pop(member, None) is not None else 0


class _FakePipeline:
    """Queues writes and applies them all on execute(), like MULTI/EXEC."""

    def __init__(self, redis: _FakeRedis) -> None:
        self.redis = redis
        self.queued: list[tuple[str, tuple[Any, ...]]] = []

    async def __aenter__(self) -> "_FakePipeline":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def zadd(self, key: str, mapping: dict[str, float]) -> "_FakePipeline":
        self.queued.append(("zadd", (key, mapping)))
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        self.queued.append(("expire", (key, seconds)))
        return self

    async def execute(self) -> list[Any]:
        assert self.redis.lock_held, "reservation must commit under the lock"
        for op, args in self.queued:
            if op == "zadd":
                self.redis._zadd(*args)
            else:
                self.redis._expire(*args)
        self.redis.executed_batches.append(len(self.queued))
        return [None] * len(self.queued)


@pytest.fixture
def redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(
        redis_pool, "get_async_redis_connection", AsyncMock(return_value=fake)
    )
    monkeypatch.setattr(redis_pool, "get_current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(redis_pool.uuid, "uuid4", lambda: _Uuid())
    monkeypatch.setattr(redis_pool.time, "time", lambda: 1_000.0)
    return fake


def test_voice_session_ttls_outlive_the_policy_cap() -> None:
    member_ttl = redis_pool.voice_session_member_ttl_seconds(POLICY)
    key_ttl = redis_pool.voice_session_key_ttl_seconds(POLICY)

    assert member_ttl == POLICY.max_session_seconds + 60
    assert key_ttl == member_ttl + 60


@pytest.mark.asyncio
async def test_acquire_admits_scopes_keys_and_locks(redis: _FakeRedis) -> None:
    member = await redis_pool.acquire_voice_session(policy=POLICY, user_id="user-7")

    assert member == "session-member-1"
    expires_at_ms = 1_000_000 + 660 * 1000
    assert redis.sets == {
        TENANT_KEY: {"session-member-1": expires_at_ms},
        USER_KEY: {"session-member-1": expires_at_ms},
    }
    assert redis.expires == {TENANT_KEY: 720, USER_KEY: 720}
    assert redis.locks == [
        {
            "name": f"{TENANT_KEY}:lock",
            "timeout": redis_pool.VOICE_SESSION_ADMISSION_LEASE_SECONDS,
            "blocking_timeout": redis_pool.VOICE_SESSION_ADMISSION_WAIT_SECONDS,
        }
    ]
    assert redis.executed_batches == [4]  # both zadds and both expires, one EXEC
    assert redis.lock_held is False


@pytest.mark.asyncio
async def test_acquire_rejects_when_tenant_is_full(redis: _FakeRedis) -> None:
    redis.sets[TENANT_KEY] = {"other-1": 9e12, "other-2": 9e12}

    with pytest.raises(redis_pool.VoiceSessionLimitExceeded) as exc_info:
        await redis_pool.acquire_voice_session(policy=POLICY, user_id="user-7")

    assert str(exc_info.value) == POLICY.limit_message
    assert redis.sets == {TENANT_KEY: {"other-1": 9e12, "other-2": 9e12}}
    assert redis.executed_batches == []


@pytest.mark.asyncio
async def test_acquire_rejects_when_user_is_full(redis: _FakeRedis) -> None:
    redis.sets[TENANT_KEY] = {"mine-1": 9e12}
    redis.sets[USER_KEY] = {"mine-1": 9e12}

    with pytest.raises(redis_pool.VoiceSessionLimitExceeded):
        await redis_pool.acquire_voice_session(policy=POLICY, user_id="user-7")

    # Rejection reserves nothing in either scope.
    assert redis.sets == {TENANT_KEY: {"mine-1": 9e12}, USER_KEY: {"mine-1": 9e12}}
    assert redis.executed_batches == []


@pytest.mark.asyncio
async def test_acquire_prunes_expired_members_first(redis: _FakeRedis) -> None:
    # Two stale members would otherwise fill the tenant budget.
    redis.sets[TENANT_KEY] = {"stale-1": 1.0, "stale-2": 2.0}

    member = await redis_pool.acquire_voice_session(policy=POLICY, user_id="user-7")

    assert set(redis.sets[TENANT_KEY]) == {member}


@pytest.mark.asyncio
async def test_release_removes_member_from_both_keys(redis: _FakeRedis) -> None:
    redis.sets[TENANT_KEY] = {"session-member-1": 9e12, "other": 9e12}
    redis.sets[USER_KEY] = {"session-member-1": 9e12}

    await redis_pool.release_voice_session(
        policy=POLICY, user_id="user-7", session_member_id="session-member-1"
    )

    assert redis.sets == {TENANT_KEY: {"other": 9e12}, USER_KEY: {}}


def test_admission_lease_outlives_the_wait() -> None:
    # A caller must never hold a lock that can expire while it still waits on
    # Redis for the same admission.
    assert (
        redis_pool.VOICE_SESSION_ADMISSION_LEASE_SECONDS
        > redis_pool.VOICE_SESSION_ADMISSION_WAIT_SECONDS
    )
