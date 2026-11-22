"""Call sites that moved from the Redis client to ``CacheBackend`` keep their
claim semantics on both backends. Each test runs once per backend."""

from uuid import uuid4

import pytest

from ee.onyx.utils import license as license_utils
from onyx.auth import login_claims_capture
from onyx.cache import factory as cache_factory
from onyx.cache.interface import CacheBackend
from onyx.cache.redis_backend import RedisCacheBackend
from onyx.configs.constants import CacheBackendType
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage import invite_rate_limit
from onyx.server.manage.invite_rate_limit import enforce_invite_rate_limit
from onyx.utils import audit, credential_audit


def test_audit_dedup_claims_the_window_once(
    cache: CacheBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cache_factory, "get_cache_backend", lambda **_: cache)
    key = f"call_site_{uuid4().hex}"

    assert audit.should_emit(key, 60, None) is True
    assert audit.should_emit(key, 60, None) is False
    assert cache.get(f"audit:{key}") == b"1"
    assert 0 < cache.ttl(f"audit:{key}") <= 60


def test_license_claim_cooldown_holds_until_cleared(
    cache: CacheBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(license_utils, "get_cache_backend", lambda: cache)
    license_utils.clear_claim_cooldown()

    try:
        assert license_utils.claim_cooldown_is_active() is False
        assert license_utils.claim_cooldown_is_active() is True
        license_utils.clear_claim_cooldown()
        assert license_utils.claim_cooldown_is_active() is False
    finally:
        license_utils.clear_claim_cooldown()


def test_claims_store_keeps_one_snapshot_per_provider(cache: CacheBackend) -> None:
    store = login_claims_capture._ClaimsStore(cache)
    key = f"idp_login_claims:tenant:{uuid4().hex}@example.com"
    try:
        assert store.snapshots(key) == {}
        assert store.snapshot(key, "openid") is None

        store.store(key, "openid", '{"n": 1}')
        store.store(key, "saml", '{"n": 2}')
        store.store(key, "openid", '{"n": 3}')

        assert store.snapshots(key) == {"openid": '{"n": 3}', "saml": '{"n": 2}'}
        assert store.snapshot(key, "saml") == '{"n": 2}'
        ttl = cache.ttl(key)
        assert 0 < ttl <= login_claims_capture._IDP_CLAIMS_TTL_SECONDS

        # A corrupt value reads as empty, and the next login replaces it.
        cache.set(key, "not json")
        assert store.snapshots(key) == {}
        store.store(key, "openid", '{"n": 4}')
        assert store.snapshots(key) == {"openid": '{"n": 4}'}
    finally:
        cache.delete(key)


def test_invite_limiter_checks_every_bucket_before_it_counts(
    cache: CacheBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(invite_rate_limit, "_INVITE_ADMIN_PER_MIN", 100)
    monkeypatch.setattr(invite_rate_limit, "_INVITE_ADMIN_PER_DAY", 5)
    monkeypatch.setattr(invite_rate_limit, "_INVITE_TENANT_PER_DAY", 100)
    admin = uuid4()
    tenant = f"tenant_{uuid4().hex}"
    tenant_key = f"ratelimit:invite_put:tenant:{tenant}:day"
    admin_day_key = f"ratelimit:invite_put:admin:{admin}:day"
    admin_min_key = f"ratelimit:invite_put:admin:{admin}:min"
    try:
        enforce_invite_rate_limit(cache, admin, num_invites=4, tenant_id=tenant)
        assert cache.get(tenant_key) == b"4"
        assert 0 < cache.ttl(admin_min_key) <= 60

        # The admin/day bucket rejects, so the tenant bucket before it stays at 4.
        with pytest.raises(OnyxError):
            enforce_invite_rate_limit(cache, admin, num_invites=2, tenant_id=tenant)
        assert cache.get(tenant_key) == b"4"
        assert cache.get(admin_day_key) == b"4"
        assert cache.get(admin_min_key) == b"1"

        enforce_invite_rate_limit(cache, admin, num_invites=1, tenant_id=tenant)
        assert cache.get(admin_day_key) == b"5"
        # The limiter released its lock: another holder can take it now.
        probe = cache.lock(invite_rate_limit._LOCK_KEY, timeout=1)
        assert probe.acquire(blocking=False)
        probe.release()
    finally:
        for key in (tenant_key, admin_day_key, admin_min_key):
            cache.delete(key)


def test_credential_audit_dedups_only_on_redis(
    cache: CacheBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PostgreSQL cache would take a second pooled connection, so there
    every event is emitted and the cache is not touched."""
    monkeypatch.setattr(cache_factory, "get_cache_backend", lambda **_: cache)
    is_redis = isinstance(cache, RedisCacheBackend)
    monkeypatch.setattr(
        credential_audit,
        "CACHE_BACKEND",
        CacheBackendType.REDIS if is_redis else CacheBackendType.POSTGRES,
    )
    row_id = uuid4().int % 1_000_000_000

    first = credential_audit._should_emit("tenant", "llm", row_id, "actor")
    second = credential_audit._should_emit("tenant", "llm", row_id, "actor")

    assert first is True
    assert second is (not is_redis)
