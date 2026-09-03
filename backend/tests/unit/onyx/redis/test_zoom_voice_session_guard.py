from unittest.mock import AsyncMock

import pytest

import onyx.redis.redis_pool as redis_pool


class _Uuid:
    hex = "session-member-1"


class _FakeRedis:
    def __init__(self, result: str | bytes = "admitted") -> None:
        self.result = result
        self.eval_calls: list[tuple[object, ...]] = []

    async def eval(self, *args: object) -> str | bytes:
        self.eval_calls.append(args)
        return self.result


def test_zoom_voice_session_ttls_derive_from_hard_session_duration() -> None:
    assert redis_pool.ZOOM_VOICE_SESSION_MAX_SECONDS == 10 * 60
    assert (
        redis_pool.ZOOM_VOICE_SESSION_MEMBER_TTL_SECONDS
        == redis_pool.ZOOM_VOICE_SESSION_MAX_SECONDS + 60
    )
    assert (
        redis_pool.ZOOM_VOICE_SESSION_KEY_TTL_SECONDS
        == redis_pool.ZOOM_VOICE_SESSION_MEMBER_TTL_SECONDS + 60
    )


@pytest.mark.asyncio
async def test_acquire_zoom_voice_session_admits_and_scopes_keys(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        redis_pool, "get_async_redis_connection", AsyncMock(return_value=redis)
    )
    monkeypatch.setattr(redis_pool, "get_current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(redis_pool.uuid, "uuid4", lambda: _Uuid())
    monkeypatch.setattr(redis_pool.time, "time", lambda: 1_000.0)

    session_member_id = await redis_pool.acquire_zoom_voice_session(
        provider_id=42, user_id="user-7"
    )

    assert session_member_id == "session-member-1"
    assert len(redis.eval_calls) == 1
    call = redis.eval_calls[0]
    assert "ZREMRANGEBYSCORE" in str(call[0])
    assert call[1:] == (
        2,
        "zoom_voice_sessions:tenant:tenant-a:provider:42",
        "zoom_voice_sessions:tenant:tenant-a:provider:42:user:user-7",
        "session-member-1",
        "1660000",
        "1000000",
        str(redis_pool.ZOOM_VOICE_SESSION_TENANT_LIMIT),
        str(redis_pool.ZOOM_VOICE_SESSION_USER_LIMIT),
        str(redis_pool.ZOOM_VOICE_SESSION_KEY_TTL_SECONDS),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [b"tenant_limit", "user_limit"])
async def test_acquire_zoom_voice_session_raises_sanitized_limit(
    monkeypatch, result: str | bytes
) -> None:
    redis = _FakeRedis(result)
    monkeypatch.setattr(
        redis_pool, "get_async_redis_connection", AsyncMock(return_value=redis)
    )
    monkeypatch.setattr(redis_pool, "get_current_tenant_id", lambda: "tenant-a")
    monkeypatch.setattr(redis_pool.uuid, "uuid4", lambda: _Uuid())

    with pytest.raises(redis_pool.ZoomVoiceSessionLimitExceeded) as exc_info:
        await redis_pool.acquire_zoom_voice_session(provider_id=42, user_id="user-7")

    assert str(exc_info.value) == redis_pool.ZOOM_VOICE_SESSION_LIMIT_MESSAGE


@pytest.mark.asyncio
async def test_release_zoom_voice_session_removes_from_scoped_keys(monkeypatch) -> None:
    redis = _FakeRedis()
    monkeypatch.setattr(
        redis_pool, "get_async_redis_connection", AsyncMock(return_value=redis)
    )
    monkeypatch.setattr(redis_pool, "get_current_tenant_id", lambda: "tenant-a")

    await redis_pool.release_zoom_voice_session(
        provider_id=42,
        user_id="user-7",
        session_member_id="session-member-1",
    )

    assert len(redis.eval_calls) == 1
    call = redis.eval_calls[0]
    assert "ZREM" in str(call[0])
    assert call[1:] == (
        2,
        "zoom_voice_sessions:tenant:tenant-a:provider:42",
        "zoom_voice_sessions:tenant:tenant-a:provider:42:user:user-7",
        "session-member-1",
    )
