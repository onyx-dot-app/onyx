"""Unit tests for the legacy-env → SSRF-level derivation in security.store.

No external deps: we monkeypatch the ``app_configs`` view (``store._cfg``) so the
derivation reads controlled values instead of the process environment.
"""

import pytest

from onyx.server.security import store
from onyx.server.security.models import SSRFProtectionLevel


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    open_url_validate_ssrf: bool = True,
    mcp_allow_private_network: bool = False,
    mcp_allow_loopback: bool = False,
    web_connector_validate_urls: str | None = None,
) -> None:
    """Pin the legacy SSRF env values the derivation reads. Defaults match the
    shipped env defaults (the all-defaults case)."""
    monkeypatch.setattr(store._cfg, "OPEN_URL_VALIDATE_SSRF", open_url_validate_ssrf)
    monkeypatch.setattr(
        store._cfg, "MCP_SERVER_ALLOW_PRIVATE_NETWORK", mcp_allow_private_network
    )
    monkeypatch.setattr(store._cfg, "MCP_SERVER_ALLOW_LOOPBACK", mcp_allow_loopback)
    monkeypatch.setattr(
        store._cfg, "WEB_CONNECTOR_VALIDATE_URLS", web_connector_validate_urls
    )


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


@pytest.mark.parametrize("web_connector_value", [None, "", "false", "true", "1"])
def test_web_connector_validate_urls_is_ignored(
    monkeypatch: pytest.MonkeyPatch, web_connector_value: str | None
) -> None:
    """WEB_CONNECTOR_VALIDATE_URLS no longer feeds the derivation; the default is
    VALIDATE_ALL regardless of its value (web-connector validation now rides on
    the level being VALIDATE_ALL)."""
    _set_env(monkeypatch, web_connector_validate_urls=web_connector_value)
    assert store._derive_ssrf_level_from_env() == SSRFProtectionLevel.VALIDATE_ALL


def test_opt_in_overrides_web_connector_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A loopback opt-in derives DISABLED regardless of the (now-ignored)
    WEB_CONNECTOR_VALIDATE_URLS value."""
    _set_env(
        monkeypatch,
        mcp_allow_loopback=True,
        web_connector_validate_urls="true",
    )
    assert store._derive_ssrf_level_from_env() == SSRFProtectionLevel.DISABLED
