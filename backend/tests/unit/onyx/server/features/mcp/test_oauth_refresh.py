"""Unit tests for proactive MCP OAuth token refresh.

Mirrors the seam-mocking style of tests/unit/external_apps/test_token_refresh.py:
the DB/Redis/HTTP seams of `oauth_refresh` are patched so the orchestration logic
(staleness, single-flight double-check, terminal-vs-transient, status updates,
endpoint resolution) is exercised without any external dependency.
"""

import copy
import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from redis.exceptions import ConnectionError as RedisConnectionError

from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPServerStatus
from onyx.oauth.errors import TokenRefreshTerminalError
from onyx.oauth.errors import TokenRefreshTransientError
from onyx.server.features.mcp import oauth_refresh as orf

TENANT = "public"
CONFIG_ID = 7
ADMIN_CONFIG_ID = 7  # equals CONFIG_ID by default → this row IS the admin row
TOKEN_ENDPOINT = "https://provider.example.com/oauth/token"


def _stale_tokens() -> dict[str, Any]:
    return {"access_token": "old", "token_type": "Bearer", "refresh_token": "rt"}


def _stale_config(**overrides: Any) -> dict[str, Any]:
    """A connection config whose access token expired in the past."""
    data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer old"},
        "tokens": _stale_tokens(),
        "client_info": {"client_id": "cid", "client_secret": "secret"},
        "token_expires_at": "2000-01-01T00:00:00+00:00",
        "token_endpoint": TOKEN_ENDPOINT,
    }
    data.update(overrides)
    return data


def _fresh_config() -> dict[str, Any]:
    data = _stale_config()
    data["token_expires_at"] = "2999-01-01T00:00:00+00:00"
    data["headers"] = {"Authorization": "Bearer ok"}
    return data


@contextmanager
def _noop_cm(*_a: Any, **_k: Any):  # type: ignore[no-untyped-def]
    yield MagicMock()


def _mcp_server(**overrides: Any) -> MagicMock:
    server = MagicMock()
    server.auth_type = MCPAuthenticationType.OAUTH
    server.id = 10
    server.server_url = "https://mcp.example.com/sse"
    server.oauth_token_endpoint = None
    server.admin_connection_config_id = ADMIN_CONFIG_ID
    for k, v in overrides.items():
        setattr(server, k, v)
    return server


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    config_sequence: list[dict[str, Any]],
) -> dict[str, MagicMock]:
    """Patch oauth_refresh's seams. `config_sequence` is the connection-config data
    returned on successive reads (pre-check, re-read under lock, persist re-read)."""
    monkeypatch.setattr(orf, "redis_shared_lock", _noop_cm)
    monkeypatch.setattr(orf, "get_session_with_tenant", _noop_cm)
    monkeypatch.setattr(
        orf, "get_connection_config_by_id", lambda cid, _db: MagicMock(id=cid)
    )
    monkeypatch.setattr(
        orf,
        "extract_connection_data",
        MagicMock(side_effect=[copy.deepcopy(c) for c in config_sequence]),
    )
    update_config = MagicMock()
    update_server = MagicMock()
    refresh = MagicMock()
    monkeypatch.setattr(orf, "update_connection_config", update_config)
    monkeypatch.setattr(orf, "update_mcp_server__no_commit", update_server)
    monkeypatch.setattr(orf, "exchange_refresh_token", refresh)
    return {
        "update_config": update_config,
        "update_server": update_server,
        "refresh": refresh,
    }


def _run(server: MagicMock | None = None) -> dict[str, str] | None:
    return orf.ensure_fresh_mcp_token(TENANT, server or _mcp_server(), CONFIG_ID)


def test_noop_when_token_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    spies = _setup(monkeypatch, config_sequence=[_fresh_config()])
    assert _run() is None
    spies["refresh"].assert_not_called()
    spies["update_config"].assert_not_called()


def test_noop_for_non_oauth_server(monkeypatch: pytest.MonkeyPatch) -> None:
    spies = _setup(monkeypatch, config_sequence=[_stale_config()])
    server = _mcp_server(auth_type=MCPAuthenticationType.API_TOKEN)
    assert _run(server) is None
    spies["refresh"].assert_not_called()


def test_noop_when_no_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _stale_config(tokens={"access_token": "old", "token_type": "Bearer"})
    spies = _setup(monkeypatch, config_sequence=[cfg])
    assert _run() is None
    spies["refresh"].assert_not_called()


def test_refreshes_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reads: pre-check, re-read under lock, persist re-read.
    spies = _setup(
        monkeypatch,
        config_sequence=[_stale_config(), _stale_config(), _stale_config()],
    )
    spies["refresh"].return_value = {
        "access_token": "new",
        "token_type": "Bearer",
        "refresh_token": "rt",
        "expires_at": 4102444800,  # 2100-01-01, epoch seconds
    }
    headers = _run()
    assert headers == {"Authorization": "Bearer new"}
    spies["refresh"].assert_called_once()
    spies["update_config"].assert_called_once()
    persisted = spies["update_config"].call_args.args[2]
    assert persisted["tokens"]["access_token"] == "new"
    assert persisted["headers"] == {"Authorization": "Bearer new"}
    assert persisted["token_expires_at"].startswith("2100-01-01")
    assert persisted["token_endpoint"] == TOKEN_ENDPOINT


def test_legacy_config_without_expiry_is_refreshed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A config predating the expiry-persistence fix: has refresh_token, no expiry.
    legacy = _stale_config()
    del legacy["token_expires_at"]
    spies = _setup(monkeypatch, config_sequence=[legacy, copy.deepcopy(legacy), legacy])
    spies["refresh"].return_value = {
        "access_token": "new",
        "token_type": "Bearer",
        "refresh_token": "rt",
        "expires_at": 4102444800,
    }
    assert _run() == {"Authorization": "Bearer new"}
    spies["refresh"].assert_called_once()


def test_double_checked_skips_when_winner_refreshed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pre-check sees stale; the re-read under the lock sees the winner's fresh token.
    spies = _setup(monkeypatch, config_sequence=[_stale_config(), _fresh_config()])
    headers = _run()
    assert headers == {"Authorization": "Bearer ok"}  # the winner's fresh headers
    spies["refresh"].assert_not_called()
    spies["update_config"].assert_not_called()


def test_terminal_marks_admin_server_awaiting_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _setup(monkeypatch, config_sequence=[_stale_config(), _stale_config()])
    spies["refresh"].side_effect = TokenRefreshTerminalError("invalid_grant")
    assert _run() is None  # does not raise
    spies["update_server"].assert_called_once()
    assert (
        spies["update_server"].call_args.kwargs["status"]
        == MCPServerStatus.AWAITING_AUTH
    )
    spies["update_config"].assert_not_called()


def test_terminal_does_not_disconnect_per_user_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This config row is NOT the admin row → don't flip global server status.
    server = _mcp_server(admin_connection_config_id=CONFIG_ID + 999)
    spies = _setup(monkeypatch, config_sequence=[_stale_config(), _stale_config()])
    spies["refresh"].side_effect = TokenRefreshTerminalError("invalid_grant")
    assert _run(server) is None
    spies["update_server"].assert_not_called()


def test_transient_keeps_existing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # A transient failure (network / 5xx / misconfigured client) must keep the token
    # and never flip the server to AWAITING_AUTH — reconnecting wouldn't help.
    spies = _setup(monkeypatch, config_sequence=[_stale_config(), _stale_config()])
    spies["refresh"].side_effect = TokenRefreshTransientError("server_error")
    assert _run() is None
    spies["update_config"].assert_not_called()
    spies["update_server"].assert_not_called()


def test_lock_contention_yields_to_winner(monkeypatch: pytest.MonkeyPatch) -> None:
    spies = _setup(monkeypatch, config_sequence=[_stale_config()])

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise orf.RedisSharedLockAcquisitionError("contended")

    monkeypatch.setattr(orf, "redis_shared_lock", _boom)
    assert _run() is None
    spies["refresh"].assert_not_called()


def test_redis_unavailable_keeps_existing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _setup(monkeypatch, config_sequence=[_stale_config()])

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RedisConnectionError("Error connecting to Redis.")

    monkeypatch.setattr(orf, "redis_shared_lock", _boom)
    assert _run() is None  # must not raise
    spies["refresh"].assert_not_called()


# ---------------------------------------------------------------------------
# Token-endpoint resolution
# ---------------------------------------------------------------------------


def test_resolve_endpoint_prefers_persisted_then_server_row() -> None:
    server = _mcp_server(oauth_token_endpoint="https://row.example.com/token")
    # Persisted config value wins.
    assert (
        orf._resolve_token_endpoint(
            server, {"headers": {}, "token_endpoint": TOKEN_ENDPOINT}
        )
        == TOKEN_ENDPOINT
    )
    # Falls back to the server row when not persisted.
    assert (
        orf._resolve_token_endpoint(server, {"headers": {}})
        == "https://row.example.com/token"
    )


def test_resolve_endpoint_discovers_when_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _mcp_server(oauth_token_endpoint=None)
    monkeypatch.setattr(orf, "validate_oauth_endpoint_url", lambda *_a, **_k: None)

    discovered = requests.Response()
    discovered.status_code = 200
    discovered._content = json.dumps({"token_endpoint": TOKEN_ENDPOINT}).encode()
    monkeypatch.setattr(orf.requests, "get", lambda *_a, **_k: discovered)

    assert orf._resolve_token_endpoint(server, {"headers": {}}) == TOKEN_ENDPOINT


def test_no_endpoint_skips_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _mcp_server(oauth_token_endpoint=None)
    cfg = _stale_config()
    del cfg["token_endpoint"]
    spies = _setup(monkeypatch, config_sequence=[cfg, copy.deepcopy(cfg)])
    # Discovery finds nothing.
    monkeypatch.setattr(orf, "_discover_token_endpoint", lambda _url: None)
    assert _run(server) is None
    spies["refresh"].assert_not_called()
