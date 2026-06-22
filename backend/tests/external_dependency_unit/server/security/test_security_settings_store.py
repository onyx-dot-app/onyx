"""Loader tests against the real Postgres-backed singleton row."""

import threading
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import SecuritySettings as SecuritySettingsRow
from onyx.server.security import store as security_store
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.server.security.store import _build_env_defaults
from onyx.server.security.store import _install_cache_for_test
from onyx.server.security.store import apply_patch
from onyx.server.security.store import get_security_settings
from onyx.server.security.store import invalidate_security_cache
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def _delete_security_settings_row() -> None:
    with get_session_with_current_tenant() as session:
        session.execute(delete(SecuritySettingsRow))
        session.commit()


@pytest.fixture(autouse=True)
def _clean_db_and_cache(
    db_session: Session,  # noqa: ARG001 — requested for side-effect (SQL engine init)
    tenant_context: None,  # noqa: ARG001 — requested for side-effect (tenant contextvar)
) -> Generator[None, None, None]:
    _delete_security_settings_row()
    invalidate_security_cache(POSTGRES_DEFAULT_SCHEMA)
    # Reset to a real-clock cache so fake-clock tests don't leak state across.
    import time as _time

    _install_cache_for_test(ttl=10.0, timer=_time.monotonic)
    yield
    _delete_security_settings_row()
    invalidate_security_cache(POSTGRES_DEFAULT_SCHEMA)


def test_empty_db_returns_env_defaults() -> None:
    """When no row exists, every field must match the env-derived default."""
    effective = get_security_settings()
    env = _build_env_defaults()
    assert effective == env


def test_partial_overrides_only_overrides_specified_fields() -> None:
    """Setting one field via the store must not perturb the others."""
    apply_patch(
        SecuritySettingsOverrides(user_directory_admin_only=True),
        present_keys={"user_directory_admin_only"},
    )
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


def test_cache_hits_avoid_db_reads() -> None:
    """Repeated loader calls within the TTL must hit the DB once."""
    get_security_settings()  # warm cache

    with patch.object(
        security_store,
        "_load_raw_overrides_unlocked",
        wraps=security_store._load_raw_overrides_unlocked,
    ) as spy:
        for _ in range(100):
            get_security_settings()
        assert spy.call_count == 0


def test_apply_patch_invalidates_cache() -> None:
    """After a write, the next load must re-read the DB."""
    get_security_settings()  # warm cache

    with patch.object(
        security_store,
        "_load_raw_overrides_unlocked",
        wraps=security_store._load_raw_overrides_unlocked,
    ) as spy:
        apply_patch(
            SecuritySettingsOverrides(user_directory_admin_only=True),
            present_keys={"user_directory_admin_only"},
        )
        # apply_patch reads existing before merging; the post-invalidate
        # read is the only additional call we care about counting.
        spy_after_write = spy.call_count
        get_security_settings()
        assert spy.call_count == spy_after_write + 1


def test_cache_ttl_expiry_triggers_reload() -> None:
    """Advancing past the TTL must force a DB re-read."""
    fake_now = [0.0]

    def fake_timer() -> float:
        return fake_now[0]

    _install_cache_for_test(ttl=5.0, timer=fake_timer)

    get_security_settings()  # warm
    with patch.object(
        security_store,
        "_load_raw_overrides_unlocked",
        wraps=security_store._load_raw_overrides_unlocked,
    ) as spy:
        fake_now[0] = 4.0  # within TTL
        get_security_settings()
        assert spy.call_count == 0
        fake_now[0] = 6.0  # past TTL
        get_security_settings()
        assert spy.call_count == 1


def test_thread_safe_concurrent_reads() -> None:
    """Many threads hammering the loader must not race or raise."""
    apply_patch(
        SecuritySettingsOverrides(user_directory_admin_only=True),
        present_keys={"user_directory_admin_only"},
    )
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
    """Multi-tenant + contextvar unset must short-circuit to env defaults
    without touching the DB."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        monkeypatch.setattr(security_store, "MULTI_TENANT", True)

        with patch.object(security_store, "_load_raw_overrides_unlocked") as spy:
            effective = get_security_settings()
            spy.assert_not_called()
        assert effective == _build_env_defaults()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_multi_tenant_default_schema_returns_env_defaults_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multi-tenant + contextvar resolved to the shared/default schema (an
    unprovisioned/unmapped user) must short-circuit to env defaults without
    touching the DB — ``public`` never carries the per-tenant table."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    try:
        monkeypatch.setattr(security_store, "MULTI_TENANT", True)

        with patch.object(security_store, "_load_raw_overrides_unlocked") as spy:
            effective = get_security_settings()
            spy.assert_not_called()
        assert effective == _build_env_defaults()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_db_error_falls_back_to_env_defaults() -> None:
    """An unexpected DB exception must not brick auth — fall back to env."""
    with patch.object(
        security_store,
        "_load_raw_overrides_unlocked",
        side_effect=RuntimeError("simulated DB outage"),
    ):
        invalidate_security_cache(POSTGRES_DEFAULT_SCHEMA)
        effective = get_security_settings()
        assert effective == _build_env_defaults()
