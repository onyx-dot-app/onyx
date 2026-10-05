import asyncio
import time
from uuid import uuid4

import pytest
from mcp.server.auth.provider import AuthorizationParams
from redis.asyncio import Redis

from onyx.mcp_oauth import attempts
from onyx.mcp_oauth.attempts import (
    allow_mcp_oauth_request,
    bind_authorization_request,
    consume_authorization_code,
    consume_authorization_request,
    get_authorization_code,
    get_authorization_request,
    store_authorization_code,
    store_authorization_request,
)
from onyx.mcp_oauth.models import (
    MCPOAuthConsentBinding,
    PendingMCPOAuthAuthorization,
    StoredMCPOAuthCode,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


def _authorization() -> PendingMCPOAuthAuthorization:
    unique_id = uuid4().hex
    return PendingMCPOAuthAuthorization(
        client_id=f"client-{unique_id}",
        client_name=f"Test client {unique_id}",
        params=AuthorizationParams(
            state=f"state-{unique_id}",
            scopes=["read:search"],
            code_challenge="a" * 43,
            redirect_uri="https://client.example.com/callback",
            redirect_uri_provided_explicitly=True,
            resource="https://onyx.example.com/mcp/",
        ),
    )


def _code_record(
    authorization: PendingMCPOAuthAuthorization | None = None,
    *,
    expires_in: float = 30,
) -> StoredMCPOAuthCode:
    return StoredMCPOAuthCode(
        authorization=authorization or _authorization(),
        user_id=uuid4(),
        tenant_id=f"tenant-{uuid4().hex}",
        expires_at=time.time() + expires_in,
    )


async def _delete_request(redis: Redis, handle: str) -> None:
    keys = attempts._request_keys(handle)
    assert keys is not None
    await redis.delete(*keys)


async def _delete_code(redis: Redis, code: str) -> None:
    key = attempts._code_key(code)
    assert key is not None
    await redis.delete(key)


async def test_authorization_request_lifecycle_binds_and_approves(
    redis_client: Redis,
) -> None:
    authorization = _authorization()
    handle = await store_authorization_request(authorization)
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"

    try:
        assert await get_authorization_request(handle) == authorization

        binding = await bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert isinstance(binding, MCPOAuthConsentBinding)
        assert "csrf_token" not in repr(binding)

        assert (
            await consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token="wrong-csrf",
            )
            is None
        )
        assert await get_authorization_request(handle) == authorization

        consumed = await consume_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
            csrf_token=binding.csrf_token,
        )
        assert consumed == authorization
        assert await get_authorization_request(handle) is None
    finally:
        await _delete_request(redis_client, handle)


async def test_non_ascii_csrf_fails_without_consuming_request(
    redis_client: Redis,
) -> None:
    authorization = _authorization()
    handle = await store_authorization_request(authorization)
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        binding = await bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert binding is not None

        assert (
            await consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token="bad-é",
            )
            is None
        )
        assert await get_authorization_request(handle) == authorization

        assert (
            await consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token=binding.csrf_token,
            )
            == authorization
        )
    finally:
        await _delete_request(redis_client, handle)


@pytest.mark.parametrize("wrong_field", ["user", "tenant", "session"])
async def test_wrong_binding_identity_cannot_consume_request(
    redis_client: Redis,
    wrong_field: str,
) -> None:
    handle = await store_authorization_request(_authorization())
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        binding = await bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert binding is not None

        assert (
            await consume_authorization_request(
                handle,
                user_id=uuid4() if wrong_field == "user" else user_id,
                tenant_id=(
                    f"tenant-{uuid4().hex}" if wrong_field == "tenant" else tenant_id
                ),
                session_hash=(
                    f"session-{uuid4().hex}"
                    if wrong_field == "session"
                    else session_hash
                ),
                csrf_token=binding.csrf_token,
            )
            is None
        )

        assert (
            await consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token=binding.csrf_token,
            )
            is not None
        )
    finally:
        await _delete_request(redis_client, handle)


async def test_binding_first_writer_wins_and_owner_must_match(
    redis_client: Redis,
) -> None:
    handle = await store_authorization_request(_authorization())
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        first = await bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert first is not None
        second = await bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert second == first
        assert (
            await bind_authorization_request(
                handle,
                user_id=uuid4(),
                tenant_id=tenant_id,
                session_hash=session_hash,
            )
            is None
        )
    finally:
        await _delete_request(redis_client, handle)


async def test_request_keys_are_hashed_and_ttl_bound(redis_client: Redis) -> None:
    handle = await store_authorization_request(_authorization())
    try:
        keys = attempts._request_keys(handle)
        assert keys is not None
        pending_key, binding_key = keys
        assert handle not in pending_key
        assert handle not in binding_key

        pending_ttl = await redis_client.ttl(pending_key)
        assert 0 < pending_ttl <= attempts.AUTHORIZATION_REQUEST_TTL_SECONDS

        binding = await bind_authorization_request(
            handle,
            user_id=uuid4(),
            tenant_id=f"tenant-{uuid4().hex}",
            session_hash=f"session-{uuid4().hex}",
        )
        assert binding is not None
        binding_ttl = await redis_client.pttl(binding_key)
        remaining_pending_ttl = await redis_client.pttl(pending_key)
        assert 0 < binding_ttl <= remaining_pending_ttl + 100
    finally:
        await _delete_request(redis_client, handle)


async def test_expired_request_cannot_be_read_or_bound(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attempts, "AUTHORIZATION_REQUEST_TTL_SECONDS", 1)
    handle = await store_authorization_request(_authorization())
    try:
        keys = attempts._request_keys(handle)
        assert keys is not None
        await redis_client.expire(keys[0], 0)
        assert await get_authorization_request(handle) is None
        assert (
            await bind_authorization_request(
                handle,
                user_id=uuid4(),
                tenant_id=f"tenant-{uuid4().hex}",
                session_hash=f"session-{uuid4().hex}",
            )
            is None
        )
    finally:
        await _delete_request(redis_client, handle)


async def test_exactly_one_concurrent_request_approval_succeeds(
    redis_client: Redis,
) -> None:
    handle = await store_authorization_request(_authorization())
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        binding = await bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert binding is not None

        results = await asyncio.gather(
            consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token=binding.csrf_token,
            ),
            consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token=binding.csrf_token,
            ),
        )
        assert sum(result is not None for result in results) == 1
    finally:
        await _delete_request(redis_client, handle)


async def test_authorization_code_lifecycle_and_hashed_storage(
    redis_client: Redis,
) -> None:
    record = _code_record()
    code = await store_authorization_code(record)
    try:
        key = attempts._code_key(code)
        assert key is not None
        assert code not in key

        raw_payload = await redis_client.get(key)
        assert isinstance(raw_payload, bytes)
        assert code.encode() not in raw_payload

        ttl = await redis_client.ttl(key)
        assert 0 < ttl <= attempts.AUTHORIZATION_CODE_TTL_SECONDS
        assert await get_authorization_code(code) == record
        assert await consume_authorization_code(code) == record
        assert await get_authorization_code(code) is None
    finally:
        await _delete_code(redis_client, code)


async def test_code_store_rejects_expired_or_overlong_records() -> None:
    with pytest.raises(ValueError, match="already expired"):
        await store_authorization_code(_code_record(expires_in=-1))
    with pytest.raises(ValueError, match="exceeds maximum"):
        await store_authorization_code(
            _code_record(expires_in=attempts.AUTHORIZATION_CODE_TTL_SECONDS + 1)
        )


async def test_expired_code_cannot_be_read_or_consumed(redis_client: Redis) -> None:
    code = await store_authorization_code(_code_record())
    try:
        key = attempts._code_key(code)
        assert key is not None
        await redis_client.set(
            key, _code_record(expires_in=-1).model_dump_json(), ex=60
        )
        assert await get_authorization_code(code) is None
        assert await consume_authorization_code(code) is None
    finally:
        await _delete_code(redis_client, code)


async def test_exactly_one_concurrent_code_exchange_succeeds(
    redis_client: Redis,
) -> None:
    code = await store_authorization_code(_code_record())
    try:
        results = await asyncio.gather(
            consume_authorization_code(code),
            consume_authorization_code(code),
        )
        assert sum(result is not None for result in results) == 1
    finally:
        await _delete_code(redis_client, code)


async def test_malformed_stored_records_fail_closed(redis_client: Redis) -> None:
    handle = await store_authorization_request(_authorization())
    code = await store_authorization_code(_code_record())
    try:
        request_keys = attempts._request_keys(handle)
        code_key = attempts._code_key(code)
        assert request_keys is not None
        assert code_key is not None
        await redis_client.set(request_keys[0], b"{not-json", ex=60)
        await redis_client.set(code_key, b'{"expires_at": "not-a-record"}', ex=60)

        assert await get_authorization_request(handle) is None
        assert await get_authorization_code(code) is None
    finally:
        await _delete_request(redis_client, handle)
        await _delete_code(redis_client, code)


async def test_random_handle_collision_fails_loudly(
    redis_client: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = "a" * 43
    keys = attempts._request_keys(handle)
    assert keys is not None
    await redis_client.set(keys[0], "occupied", ex=60)
    monkeypatch.setattr(attempts, "_new_handle", lambda: handle)
    try:
        with pytest.raises(RuntimeError, match="collision"):
            await store_authorization_request(_authorization())
    finally:
        await redis_client.delete(*keys)


async def test_invalid_handles_do_not_touch_redis() -> None:
    bad_handle = "not-valid"
    assert await get_authorization_request(bad_handle) is None
    assert (
        await bind_authorization_request(
            bad_handle,
            user_id=uuid4(),
            tenant_id="tenant",
            session_hash="session",
        )
        is None
    )
    assert (
        await consume_authorization_request(
            bad_handle,
            user_id=uuid4(),
            tenant_id="tenant",
            session_hash="session",
            csrf_token="csrf",
        )
        is None
    )
    assert await get_authorization_code(bad_handle) is None
    assert await consume_authorization_code(bad_handle) is None


async def test_rate_limit_counter_has_atomic_ttl(
    redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = f"bucket-{uuid4().hex}"
    window_seconds = 60
    frozen_now = time.time()
    monkeypatch.setattr(attempts.time, "time", lambda: frozen_now)
    key = attempts._rate_key(bucket, window_seconds)
    try:
        assert await allow_mcp_oauth_request(
            bucket, limit=2, window_seconds=window_seconds
        )
        assert await allow_mcp_oauth_request(
            bucket, limit=2, window_seconds=window_seconds
        )
        assert not await allow_mcp_oauth_request(
            bucket, limit=2, window_seconds=window_seconds
        )

        ttl = await redis_client.ttl(key)
        assert 0 < ttl <= window_seconds
    finally:
        await redis_client.delete(key)


async def test_rate_limit_rejects_invalid_limits() -> None:
    bucket = f"bucket-{uuid4().hex}"
    with pytest.raises(ValueError, match="positive"):
        await allow_mcp_oauth_request(bucket, limit=0, window_seconds=60)
    with pytest.raises(ValueError, match="positive"):
        await allow_mcp_oauth_request(bucket, limit=1, window_seconds=0)
