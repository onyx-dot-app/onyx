"""Unit tests for the legacy-env → SSRF-level derivation in security.store.

No external deps: we monkeypatch the ``app_configs`` view (``store._cfg``) so the
derivation reads controlled values instead of the process environment.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from onyx.server.security import store
from onyx.server.security.models import SecuritySettingsOverrides, SSRFProtectionLevel


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    open_url_validate_ssrf: bool = True,
    mcp_allow_private_network: bool = False,
    mcp_allow_loopback: bool = False,
) -> None:
    """Pin the legacy SSRF env values the derivation reads. Defaults match the
    shipped env defaults (the all-defaults case)."""
    monkeypatch.setattr(store._cfg, "OPEN_URL_VALIDATE_SSRF", open_url_validate_ssrf)
    monkeypatch.setattr(
        store._cfg, "MCP_SERVER_ALLOW_PRIVATE_NETWORK", mcp_allow_private_network
    )
    monkeypatch.setattr(store._cfg, "MCP_SERVER_ALLOW_LOOPBACK", mcp_allow_loopback)


def test_all_defaults_is_validate_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Secure by default: with no legacy opt-in, the default is VALIDATE_ALL."""
    _set_env(monkeypatch)
    assert store._derive_ssrf_level_from_env() == SSRFProtectionLevel.VALIDATE_ALL


def test_open_url_opt_out_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, open_url_validate_ssrf=False)
    assert store._derive_ssrf_level_from_env() == SSRFProtectionLevel.DISABLED


def test_mcp_private_network_allows_private_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Private-network opt-in without loopback maps to the in-between level —
    MCP reaches RFC1918 hosts, loopback stays blocked."""
    _set_env(monkeypatch, mcp_allow_private_network=True)
    assert (
        store._derive_ssrf_level_from_env() == SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK
    )


def test_mcp_loopback_alone_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loopback opt-in alone is enough — it grants access only DISABLED allows."""
    _set_env(monkeypatch, mcp_allow_loopback=True)
    assert store._derive_ssrf_level_from_env() == SSRFProtectionLevel.DISABLED


def test_mcp_private_and_loopback_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loopback opt-in wins over the private-network opt-in — it needs DISABLED."""
    _set_env(monkeypatch, mcp_allow_private_network=True, mcp_allow_loopback=True)
    assert store._derive_ssrf_level_from_env() == SSRFProtectionLevel.DISABLED


def test_llm_env_injection_forced_off_on_multi_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """merge_with_env forces injection off on multi-tenant even when a stored
    override says enabled."""
    monkeypatch.setattr(store, "MULTI_TENANT", True)
    overrides = SecuritySettingsOverrides(llm_custom_config_env_injection=True)
    assert store.merge_with_env(overrides).llm_custom_config_env_injection is False


def test_llm_env_injection_defaults_on_for_single_tenant() -> None:
    assert (
        store.merge_with_env(
            SecuritySettingsOverrides()
        ).llm_custom_config_env_injection
        is True
    )


def test_llm_env_injection_hard_off_on_multi_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MULTI_TENANT clamp wins even if a stored setting says enabled."""
    monkeypatch.setattr(store, "MULTI_TENANT", True)
    assert store.llm_custom_config_env_injection_enabled() is False


def test_llm_env_injection_follows_setting_on_single_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store, "MULTI_TENANT", False)
    for enabled in (True, False):
        monkeypatch.setattr(
            store,
            "get_security_settings",
            lambda enabled=enabled: store._build_env_defaults().model_copy(
                update={"llm_custom_config_env_injection": enabled}
            ),
        )
        assert store.llm_custom_config_env_injection_enabled() is enabled


def test_llm_env_injection_invariant_violation_logs_critical(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the effective settings ever claim injection is enabled on
    multi-tenant, the accessor still returns False and screams about it."""
    monkeypatch.setattr(store, "MULTI_TENANT", True)
    monkeypatch.setattr(
        store,
        "get_security_settings",
        lambda: store._build_env_defaults().model_copy(
            update={"llm_custom_config_env_injection": True}
        ),
    )
    with caplog.at_level(logging.CRITICAL):
        assert store.llm_custom_config_env_injection_enabled() is False
    assert any(
        record.levelno == logging.CRITICAL and "Invariant violation" in record.message
        for record in caplog.records
    )


def test_llm_env_injection_no_critical_log_when_invariant_holds(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(store, "MULTI_TENANT", True)
    with caplog.at_level(logging.CRITICAL):
        assert store.llm_custom_config_env_injection_enabled() is False
    assert not caplog.records


def _set_jwt_env(
    monkeypatch: pytest.MonkeyPatch,
    url: str | None = None,
    audience: str | None = None,
    issuer: str | None = None,
) -> None:
    monkeypatch.setattr(store._cfg, "JWT_PUBLIC_KEY_URL", url)
    monkeypatch.setattr(store._cfg, "JWT_EXPECTED_AUDIENCE", audience)
    monkeypatch.setattr(store._cfg, "JWT_EXPECTED_ISSUER", issuer)


def test_env_pin_wins_over_stored_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_jwt_env(monkeypatch, audience="env-aud")
    overrides = SecuritySettingsOverrides(jwt_expected_audience="db-aud")
    assert store.merge_with_env(overrides).jwt_expected_audience == "env-aud"


def test_db_override_is_truth_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_jwt_env(monkeypatch)
    overrides = SecuritySettingsOverrides(
        jwt_public_key_url="https://idp/keys", jwt_expected_issuer="https://idp"
    )
    effective = store.merge_with_env(overrides)
    assert effective.jwt_public_key_url == "https://idp/keys"
    assert effective.jwt_expected_issuer == "https://idp"
    assert effective.jwt_expected_audience is None


def test_unset_everywhere_means_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_jwt_env(monkeypatch)
    effective = store.merge_with_env(SecuritySettingsOverrides())
    assert effective.jwt_public_key_url is None
    assert effective.jwt_expected_audience is None
    assert effective.jwt_expected_issuer is None


def test_env_pinned_active_fields_track_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_jwt_env(monkeypatch, url="https://idp/keys", issuer="https://idp")
    assert store.env_pinned_active_fields() == {
        "jwt_public_key_url",
        "jwt_expected_issuer",
    }
    _set_jwt_env(monkeypatch)
    assert store.env_pinned_active_fields() == frozenset()


@pytest.fixture
def seed_seams(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """In-memory stand-ins for the DB row, KV overlay, and distributed lock."""
    state: dict[str, Any] = {"row": SecuritySettingsOverrides(), "writes": 0}

    @contextmanager
    def fake_lock() -> Iterator[None]:
        yield

    def fake_load() -> SecuritySettingsOverrides:
        return state["row"]

    def fake_store(overrides: SecuritySettingsOverrides) -> None:
        state["row"] = overrides
        state["writes"] += 1

    monkeypatch.setattr(store, "security_settings_write_lock", fake_lock)
    monkeypatch.setattr(store, "_load_raw_overrides_unlocked", fake_load)
    monkeypatch.setattr(store, "_store_overrides_unlocked", fake_store)
    return state


def test_seed_writes_env_values_once(
    monkeypatch: pytest.MonkeyPatch, seed_seams: dict[str, Any]
) -> None:
    _set_jwt_env(monkeypatch, url="https://idp/keys", audience="aud")
    store.seed_jwt_settings_from_env()
    assert seed_seams["row"].jwt_public_key_url == "https://idp/keys"
    assert seed_seams["row"].jwt_expected_audience == "aud"
    assert seed_seams["writes"] == 1

    store.seed_jwt_settings_from_env()
    assert seed_seams["writes"] == 1


def test_seed_resyncs_a_changed_env_value(
    monkeypatch: pytest.MonkeyPatch, seed_seams: dict[str, Any]
) -> None:
    seed_seams["row"] = SecuritySettingsOverrides(jwt_public_key_url="https://old")
    _set_jwt_env(monkeypatch, url="https://new")
    store.seed_jwt_settings_from_env()
    assert seed_seams["row"].jwt_public_key_url == "https://new"


def test_seed_skips_entirely_when_env_unset(
    monkeypatch: pytest.MonkeyPatch, seed_seams: dict[str, Any]
) -> None:
    _set_jwt_env(monkeypatch)
    store.seed_jwt_settings_from_env()
    assert seed_seams["writes"] == 0


def test_seed_noop_on_multi_tenant(
    monkeypatch: pytest.MonkeyPatch, seed_seams: dict[str, Any]
) -> None:
    monkeypatch.setattr(store, "MULTI_TENANT", True)
    _set_jwt_env(monkeypatch, url="https://idp/keys")
    store.seed_jwt_settings_from_env()
    assert seed_seams["writes"] == 0


def test_seed_failure_never_raises(
    monkeypatch: pytest.MonkeyPatch, seed_seams: dict[str, Any]
) -> None:
    def boom() -> SecuritySettingsOverrides:
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "_load_raw_overrides_unlocked", boom)
    _set_jwt_env(monkeypatch, url="https://idp/keys")
    store.seed_jwt_settings_from_env()
    assert seed_seams["writes"] == 0
