import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from mcp.server.auth.provider import AuthorizationParams

from onyx.cache.interface import CacheBackend
from onyx.cache.postgres_backend import PostgresCacheBackend
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.oauth_provider import attempts
from onyx.oauth_provider.attempts import (
    bind_authorization_request,
    consume_authorization_code,
    consume_authorization_request,
    get_authorization_code,
    get_authorization_request,
    store_authorization_code,
    store_authorization_request,
)
from onyx.oauth_provider.models import (
    OAuthProviderConsentBinding,
    PendingOAuthProviderAuthorization,
    StoredOAuthProviderCode,
)
from onyx.redis.redis_pool import redis_pool
from shared_configs.configs import DEFAULT_REDIS_PREFIX, POSTGRES_DEFAULT_SCHEMA


@pytest.fixture(params=["redis", "postgres"])
def cache(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> CacheBackend:
    if request.param == "redis":
        backend: CacheBackend = RedisCacheBackend(
            redis_pool.get_client(DEFAULT_REDIS_PREFIX)
        )
    else:
        request.getfixturevalue("db_session")
        backend = PostgresCacheBackend(POSTGRES_DEFAULT_SCHEMA)
    monkeypatch.setattr(attempts, "get_shared_cache_backend", lambda: backend)
    return backend


def _authorization() -> PendingOAuthProviderAuthorization:
    unique_id = uuid4().hex
    return PendingOAuthProviderAuthorization(
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
    authorization: PendingOAuthProviderAuthorization | None = None,
    *,
    expires_in: float = 30,
) -> StoredOAuthProviderCode:
    return StoredOAuthProviderCode(
        authorization=authorization or _authorization(),
        user_id=uuid4(),
        tenant_id=f"tenant-{uuid4().hex}",
        expires_at=time.time() + expires_in,
    )


def _delete_request(cache: CacheBackend, handle: str) -> None:
    keys = attempts._request_keys(handle)
    assert keys is not None
    for key in keys:
        cache.delete(key)


def _delete_code(cache: CacheBackend, code: str) -> None:
    key = attempts._code_key(code)
    assert key is not None
    cache.delete(key)


def test_authorization_request_lifecycle_binds_and_approves(
    cache: CacheBackend,
) -> None:
    authorization = _authorization()
    handle = store_authorization_request(authorization)
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"

    try:
        assert get_authorization_request(handle) == authorization

        binding = bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert isinstance(binding, OAuthProviderConsentBinding)
        assert "csrf_token" not in repr(binding)

        assert (
            consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token="wrong-csrf",
            )
            is None
        )
        assert get_authorization_request(handle) == authorization

        consumed = consume_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
            csrf_token=binding.csrf_token,
        )
        assert consumed == authorization
        assert get_authorization_request(handle) is None
    finally:
        _delete_request(cache, handle)


def test_non_ascii_csrf_fails_without_consuming_request(
    cache: CacheBackend,
) -> None:
    authorization = _authorization()
    handle = store_authorization_request(authorization)
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        binding = bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert binding is not None

        assert (
            consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token="bad-é",
            )
            is None
        )
        assert get_authorization_request(handle) == authorization

        assert (
            consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token=binding.csrf_token,
            )
            == authorization
        )
    finally:
        _delete_request(cache, handle)


@pytest.mark.parametrize("wrong_field", ["user", "tenant", "session"])
def test_wrong_binding_identity_cannot_consume_request(
    cache: CacheBackend,
    wrong_field: str,
) -> None:
    handle = store_authorization_request(_authorization())
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        binding = bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert binding is not None

        assert (
            consume_authorization_request(
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
            consume_authorization_request(
                handle,
                user_id=user_id,
                tenant_id=tenant_id,
                session_hash=session_hash,
                csrf_token=binding.csrf_token,
            )
            is not None
        )
    finally:
        _delete_request(cache, handle)


def test_binding_first_writer_wins_and_owner_must_match(
    cache: CacheBackend,
) -> None:
    handle = store_authorization_request(_authorization())
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        first = bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert first is not None
        second = bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert second == first
        assert (
            bind_authorization_request(
                handle,
                user_id=uuid4(),
                tenant_id=tenant_id,
                session_hash=session_hash,
            )
            is None
        )
    finally:
        _delete_request(cache, handle)


def test_request_keys_are_hashed_and_ttl_bound(cache: CacheBackend) -> None:
    handle = store_authorization_request(_authorization())
    try:
        keys = attempts._request_keys(handle)
        assert keys is not None
        pending_key, binding_key = keys
        assert handle not in pending_key
        assert handle not in binding_key

        pending_ttl = cache.ttl(pending_key)
        assert 0 < pending_ttl <= attempts.AUTHORIZATION_REQUEST_TTL_SECONDS

        binding = bind_authorization_request(
            handle,
            user_id=uuid4(),
            tenant_id=f"tenant-{uuid4().hex}",
            session_hash=f"session-{uuid4().hex}",
        )
        assert binding is not None
        binding_ttl = cache.ttl(binding_key)
        assert 0 < binding_ttl <= cache.ttl(pending_key) + 1
    finally:
        _delete_request(cache, handle)


def test_expired_request_cannot_be_read_or_bound(
    cache: CacheBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attempts, "AUTHORIZATION_REQUEST_TTL_SECONDS", 1)
    handle = store_authorization_request(_authorization())
    try:
        keys = attempts._request_keys(handle)
        assert keys is not None
        cache.expire(keys[0], 0)
        assert get_authorization_request(handle) is None
        assert (
            bind_authorization_request(
                handle,
                user_id=uuid4(),
                tenant_id=f"tenant-{uuid4().hex}",
                session_hash=f"session-{uuid4().hex}",
            )
            is None
        )
    finally:
        _delete_request(cache, handle)


def test_exactly_one_concurrent_request_approval_succeeds(
    cache: CacheBackend,
) -> None:
    handle = store_authorization_request(_authorization())
    user_id = uuid4()
    tenant_id = f"tenant-{uuid4().hex}"
    session_hash = f"session-{uuid4().hex}"
    try:
        binding = bind_authorization_request(
            handle,
            user_id=user_id,
            tenant_id=tenant_id,
            session_hash=session_hash,
        )
        assert binding is not None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: consume_authorization_request(
                        handle,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        session_hash=session_hash,
                        csrf_token=binding.csrf_token,
                    ),
                    range(2),
                )
            )
        assert sum(result is not None for result in results) == 1
    finally:
        _delete_request(cache, handle)


def test_authorization_code_lifecycle_and_hashed_storage(
    cache: CacheBackend,
) -> None:
    record = _code_record()
    code = store_authorization_code(record)
    try:
        key = attempts._code_key(code)
        assert key is not None
        assert code not in key

        raw_payload = cache.get(key)
        assert isinstance(raw_payload, bytes)
        assert code.encode() not in raw_payload

        ttl = cache.ttl(key)
        assert 0 < ttl <= attempts.AUTHORIZATION_CODE_TTL_SECONDS
        assert get_authorization_code(code) == record
        assert consume_authorization_code(code) == record
        assert get_authorization_code(code) is None
    finally:
        _delete_code(cache, code)


def test_code_store_rejects_expired_or_overlong_records() -> None:
    with pytest.raises(ValueError, match="already expired"):
        store_authorization_code(_code_record(expires_in=-1))
    with pytest.raises(ValueError, match="exceeds maximum"):
        store_authorization_code(
            _code_record(expires_in=attempts.AUTHORIZATION_CODE_TTL_SECONDS + 1)
        )


def test_expired_code_cannot_be_read_or_consumed(cache: CacheBackend) -> None:
    code = store_authorization_code(_code_record())
    try:
        key = attempts._code_key(code)
        assert key is not None
        cache.set(key, _code_record(expires_in=-1).model_dump_json(), ex=60)
        assert get_authorization_code(code) is None
        assert consume_authorization_code(code) is None
    finally:
        _delete_code(cache, code)


def test_exactly_one_concurrent_code_exchange_succeeds(
    cache: CacheBackend,
) -> None:
    code = store_authorization_code(_code_record())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda _: consume_authorization_code(code), range(2))
            )
        assert sum(result is not None for result in results) == 1
    finally:
        _delete_code(cache, code)


def test_malformed_stored_records_fail_closed(cache: CacheBackend) -> None:
    handle = store_authorization_request(_authorization())
    code = store_authorization_code(_code_record())
    try:
        request_keys = attempts._request_keys(handle)
        code_key = attempts._code_key(code)
        assert request_keys is not None
        assert code_key is not None
        cache.set(request_keys[0], b"{not-json", ex=60)
        cache.set(code_key, b'{"expires_at": "not-a-record"}', ex=60)

        assert get_authorization_request(handle) is None
        assert get_authorization_code(code) is None
    finally:
        _delete_request(cache, handle)
        _delete_code(cache, code)


def test_random_handle_collision_fails_loudly(
    cache: CacheBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = "a" * 43
    keys = attempts._request_keys(handle)
    assert keys is not None
    cache.set(keys[0], "occupied", ex=60)
    monkeypatch.setattr(attempts.secrets, "token_urlsafe", lambda _: handle)
    try:
        with pytest.raises(RuntimeError, match="collision"):
            store_authorization_request(_authorization())
    finally:
        for key in keys:
            cache.delete(key)


def test_invalid_handles_do_not_touch_the_cache() -> None:
    bad_handle = "not-valid"
    assert get_authorization_request(bad_handle) is None
    assert (
        bind_authorization_request(
            bad_handle,
            user_id=uuid4(),
            tenant_id="tenant",
            session_hash="session",
        )
        is None
    )
    assert (
        consume_authorization_request(
            bad_handle,
            user_id=uuid4(),
            tenant_id="tenant",
            session_hash="session",
            csrf_token="csrf",
        )
        is None
    )
    assert get_authorization_code(bad_handle) is None
    assert consume_authorization_code(bad_handle) is None
