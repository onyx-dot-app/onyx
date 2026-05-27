"""Tests for the runtime security settings loader.

Exercises cache behavior, env fallback, multi-tenant pre-tenant safety, and
KV-failure resilience using a real KV backend (Postgres-backed). The store
exposes _install_cache_for_test for fake-clock TTL testing.
"""

import threading
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from onyx.configs.constants import KV_SECURITY_SETTINGS_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.security import store as security_store
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.server.security.store import _build_env_defaults
from onyx.server.security.store import _install_cache_for_test
from onyx.server.security.store import get_security_settings
from onyx.server.security.store import invalidate_security_cache
from onyx.server.security.store import store_overrides
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.constants import TEST_TENANT_ID


@pytest.fixture(autouse=True)
def _clean_kv_and_cache(
    tenant_context: None,  # noqa: ARG001 — requested for tenant-contextvar side effect
) -> Generator[None, None, None]:
    """Clean state before and after each test:
    - Wipe any KV blob for this tenant.
    - Invalidate the in-process cache entry.
    - Reinstall a fresh TTLCache to clear any prior fake-clock state.
    """
    kv = get_kv_store()
    try:
        kv.delete(KV_SECURITY_SETTINGS_KEY)
    except KvKeyNotFoundError:
        pass
    invalidate_security_cache(TEST_TENANT_ID)
    # Reinstall a stock cache so tests using a fake clock don't leak state.
    import time as _time

    _install_cache_for_test(ttl=10.0, timer=_time.monotonic)
    yield
    try:
        kv.delete(KV_SECURITY_SETTINGS_KEY)
    except KvKeyNotFoundError:
        pass
    invalidate_security_cache(TEST_TENANT_ID)


def test_empty_kv_returns_env_defaults() -> None:
    """When no KV blob exists, every field must match the env-derived default."""
    effective = get_security_settings()
    env = _build_env_defaults()
    assert effective == env


def test_partial_kv_only_overrides_specified_fields() -> None:
    """Setting one field via the store must not perturb the others."""
    store_overrides(SecuritySettingsOverrides(user_directory_admin_only=True))
    effective = get_security_settings()
    env = _build_env_defaults()

    assert effective.user_directory_admin_only is True
    # All other fields fall back to env.
    assert effective.track_external_idp_expiry == env.track_external_idp_expiry
    assert effective.mask_credential_prefix == env.mask_credential_prefix
    assert effective.valid_email_domains == env.valid_email_domains
    assert effective.password_min_length == env.password_min_length
    assert effective.password_max_length == env.password_max_length
    assert effective.password_require_uppercase == env.password_require_uppercase


def test_cache_hits_avoid_kv_reads() -> None:
    """Repeated loader calls within the TTL must hit KV once."""
    get_security_settings()  # warm cache

    with patch.object(
        security_store, "load_raw_overrides", wraps=security_store.load_raw_overrides
    ) as spy:
        for _ in range(100):
            get_security_settings()
        assert spy.call_count == 0


def test_store_overrides_invalidates_cache() -> None:
    """After a write, the next load must re-read KV (cache invalidated)."""
    get_security_settings()  # warm cache

    with patch.object(
        security_store, "load_raw_overrides", wraps=security_store.load_raw_overrides
    ) as spy:
        store_overrides(SecuritySettingsOverrides(user_directory_admin_only=True))
        get_security_settings()
        # First call is from inside store_overrides? No, store_overrides only writes.
        # The first KV read after invalidation should be by get_security_settings.
        assert spy.call_count == 1


def test_cache_ttl_expiry_triggers_reload() -> None:
    """Advancing the fake clock past the TTL must force a KV re-read."""
    fake_now = [0.0]

    def fake_timer() -> float:
        return fake_now[0]

    _install_cache_for_test(ttl=5.0, timer=fake_timer)

    get_security_settings()  # warm
    with patch.object(
        security_store, "load_raw_overrides", wraps=security_store.load_raw_overrides
    ) as spy:
        # Within TTL → cache hit.
        fake_now[0] = 4.0
        get_security_settings()
        assert spy.call_count == 0
        # Past TTL → cache miss → KV read.
        fake_now[0] = 6.0
        get_security_settings()
        assert spy.call_count == 1


def test_thread_safe_concurrent_reads() -> None:
    """Many threads hammering the loader must not race or raise."""
    store_overrides(SecuritySettingsOverrides(user_directory_admin_only=True))
    results: list[Any] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(50):
                results.append(get_security_settings().user_directory_admin_only)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert all(v is True for v in results)


def test_effective_settings_are_frozen() -> None:
    """Cached SecuritySettings instances must be immutable from caller code."""
    settings = get_security_settings()
    with pytest.raises(ValidationError):
        settings.user_directory_admin_only = True  # type: ignore[misc]


def test_pre_tenant_returns_env_defaults_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In multi-tenant mode with no tenant contextvar, loader must return env
    defaults without raising and without touching KV."""
    # Reset the contextvar to "unset" (None) for this test.
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        # Make is_multi_tenant() return True by patching the local binding.
        import shared_configs.contextvars as ctx

        monkeypatch.setattr(ctx, "MULTI_TENANT", True, raising=False)

        with patch.object(security_store, "load_raw_overrides") as spy:
            effective = get_security_settings()
            spy.assert_not_called()
        assert effective == _build_env_defaults()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_kv_error_falls_back_to_env_defaults() -> None:
    """An unexpected KV exception must not brick auth — fall back to env."""
    with patch.object(
        security_store,
        "load_raw_overrides",
        side_effect=RuntimeError("simulated KV outage"),
    ):
        invalidate_security_cache(TEST_TENANT_ID)
        effective = get_security_settings()
        assert effective == _build_env_defaults()
