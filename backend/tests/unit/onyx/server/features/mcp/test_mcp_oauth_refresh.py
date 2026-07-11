"""Unit tests for transport-independent MCP OAuth refresh.

The SDK OAuthClientProvider that drives refresh is disabled for SSE transport,
so an SSE server's access token never rotates and tool calls start failing
once the token expires. refresh_mcp_oauth_token_if_expired performs the
refresh directly. These tests mock the DB layer and the token endpoint, so no
services are required.
"""

import time
from types import SimpleNamespace
from typing import Any
from typing import cast

import pytest

import onyx.server.features.mcp.api as mcp_api
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.models import MCPServer as DbMCPServer
from onyx.server.features.mcp.api import refresh_mcp_oauth_token_if_expired
from onyx.server.features.mcp.models import MCPOAuthKeys

_TOKEN_ENDPOINT = "https://gitlab.example.com/oauth/token"


class _FakeSession:
    """Just enough Session for the row-lock statement in the refresh path."""

    def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalar_one=lambda: object())


def _server_stub() -> DbMCPServer:
    return cast(
        DbMCPServer,
        SimpleNamespace(
            name="gitlab",
            oauth_provider_mode=MCPOAuthProviderMode.KNOWN_PROVIDER,
            oauth_token_endpoint=_TOKEN_ENDPOINT,
        ),
    )


def _install_mocks(
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict[str, Any],
    *,
    refresh_response: dict[str, Any] | None,
) -> dict[str, Any]:
    """Patch the DB accessors + token endpoint the refresh helper touches.

    Returns a ``captured`` dict recording the outbound POST and the persisted
    config so tests can assert on them.
    """
    captured: dict[str, Any] = {"post_called": False}

    monkeypatch.setattr(
        mcp_api,
        "get_connection_config_by_id",
        lambda config_id, _db_session: SimpleNamespace(id=config_id),
    )
    # extract_connection_data returns the same dict the helper mutates in place.
    monkeypatch.setattr(
        mcp_api,
        "extract_connection_data",
        lambda _config, _apply_mask=False: config_data,
    )
    monkeypatch.setattr(mcp_api, "validate_oauth_endpoint_url", lambda _url: None)

    def _fake_update(config_id: int, _db_session: Any, data: Any = None) -> Any:
        captured["updated_config_data"] = data
        return SimpleNamespace(id=config_id)

    monkeypatch.setattr(mcp_api, "update_connection_config", _fake_update)

    class _Resp:
        def json(self) -> dict[str, Any]:
            return refresh_response or {}

        def raise_for_status(self) -> None:
            return None

    def _fake_post(url: str, data: Any = None, **_kwargs: Any) -> Any:
        captured["post_called"] = True
        captured["url"] = url
        captured["data"] = data
        return _Resp()

    monkeypatch.setattr(mcp_api.requests, "post", _fake_post)
    return captured


def test_refreshes_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,  # expired
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "client_secret": "csecret",
        },
    }
    captured = _install_mocks(
        monkeypatch,
        config_data,
        refresh_response={
            "access_token": "NEW",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "REFRESH_2",
            "scope": "api",
        },
    )

    header = refresh_mcp_oauth_token_if_expired(
        _server_stub(), 42, db_session=cast(Any, _FakeSession())
    )

    assert header == "Bearer NEW"
    # Outbound refresh POST is a correct grant_type=refresh_token exchange.
    assert captured["url"] == _TOKEN_ENDPOINT
    assert captured["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "REFRESH_1",
        "client_id": "cid",
        "client_secret": "csecret",
    }
    # Rotated token + header are persisted for the next call.
    persisted = captured["updated_config_data"]
    assert persisted[MCPOAuthKeys.TOKENS.value]["access_token"] == "NEW"
    assert persisted[MCPOAuthKeys.TOKENS.value]["refresh_token"] == "REFRESH_2"
    assert persisted["headers"]["Authorization"] == "Bearer NEW"
    assert persisted[MCPOAuthKeys.TOKEN_EXPIRES_AT.value] > time.time()


def test_no_refresh_when_token_still_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() + 3600,  # still valid
        MCPOAuthKeys.CLIENT_INFO.value: {"client_id": "cid"},
    }
    captured = _install_mocks(monkeypatch, config_data, refresh_response=None)

    header = refresh_mcp_oauth_token_if_expired(
        _server_stub(), 42, db_session=cast(Any, _FakeSession())
    )

    assert header is None
    assert captured["post_called"] is False


def test_no_refresh_without_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {"access_token": "OLD", "token_type": "Bearer"},
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {"client_id": "cid"},
    }
    captured = _install_mocks(monkeypatch, config_data, refresh_response=None)

    header = refresh_mcp_oauth_token_if_expired(
        _server_stub(), 42, db_session=cast(Any, _FakeSession())
    )

    assert header is None
    assert captured["post_called"] is False


def test_refresh_preserves_static_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A connection can carry static headers alongside Authorization; a
    refresh must merge the new header in, not replace the whole map."""
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD", "X-Custom": "static-value"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {"client_id": "cid"},
    }
    _install_mocks(
        monkeypatch,
        config_data,
        refresh_response={
            "access_token": "NEW",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "REFRESH_2",
        },
    )

    header = refresh_mcp_oauth_token_if_expired(
        _server_stub(), 42, db_session=cast(Any, _FakeSession())
    )

    assert header == "Bearer NEW"
    assert config_data["headers"] == {
        "Authorization": "Bearer NEW",
        "X-Custom": "static-value",
    }
