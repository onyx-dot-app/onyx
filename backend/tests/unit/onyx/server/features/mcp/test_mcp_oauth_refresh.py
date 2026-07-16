"""Regression coverage for SSE-transport MCP OAuth refresh: SSE can't use the
SDK's httpx.Auth refresh (open stream), so refresh_mcp_oauth_token_if_expired
drives OAuthClientProvider's refresh step directly instead.

Exercises the real OAuthClientProvider/OAuthContext/OnyxTokenStorage code —
client-auth-method branching, endpoint resolution, persistence — mocking only
the DB layer and the outbound network call.
"""

import time
from types import SimpleNamespace
from typing import Any
from typing import cast
from urllib.parse import parse_qs

import httpx
import pytest

import onyx.server.features.mcp.oauth as mcp_oauth
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.models import MCPServer as DbMCPServer
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.server.features.mcp.oauth import refresh_mcp_oauth_token_if_expired

_TOKEN_ENDPOINT = "https://gitlab.example.com/oauth/token"
_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"


def _server_stub() -> DbMCPServer:
    # AUTO_DISCOVERY: token endpoint comes from persisted METADATA, matching
    # real DCR-registered servers (KNOWN_PROVIDER never negotiates
    # client_secret_basic — see _build_oauth_admin_config_data).
    return cast(
        DbMCPServer,
        SimpleNamespace(
            name="gitlab",
            server_url="https://mcp.gitlab.example.com",
            oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
            oauth_authorization_endpoint=None,
            oauth_token_endpoint=None,
        ),
    )


class _FakeDbSession:
    def __enter__(self) -> "_FakeDbSession":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None


class _FakeAsyncHttpClient:
    """Captures the refresh httpx.Request and returns a canned response."""

    def __init__(self, response: httpx.Response, captured: dict[str, Any]):
        self._response = response
        self._captured = captured

    async def __aenter__(self) -> "_FakeAsyncHttpClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def send(self, request: httpx.Request) -> httpx.Response:
        self._captured["sent_request"] = request
        return self._response


def _install_mocks(
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict[str, Any],
    *,
    response: httpx.Response | None,
) -> dict[str, Any]:
    """Patch the DB layer OnyxTokenStorage uses and the outbound network call;
    the real OAuthClientProvider/OAuthContext/OnyxTokenStorage code runs
    untouched. Returns a dict capturing the outbound request + persisted config.
    """
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        mcp_oauth, "get_session_with_current_tenant", lambda: _FakeDbSession()
    )
    monkeypatch.setattr(
        mcp_oauth,
        "get_connection_config_by_id",
        lambda config_id, _db_session: SimpleNamespace(id=config_id),
    )
    # extract_connection_data returns the same dict the SDK storage mutates.
    monkeypatch.setattr(
        mcp_oauth,
        "extract_connection_data",
        lambda _config, _apply_mask=False: config_data,
    )

    def _fake_update(config_id: int, _db_session: Any, data: Any = None) -> Any:
        captured["updated_config_data"] = data
        return SimpleNamespace(id=config_id)

    monkeypatch.setattr(mcp_oauth, "update_connection_config", _fake_update)

    fake_client = _FakeAsyncHttpClient(response or httpx.Response(400), captured)
    monkeypatch.setattr(mcp_oauth, "mcp_ssrf_httpx_client_factory", lambda: fake_client)
    return captured


def _token_response(**overrides: Any) -> httpx.Response:
    payload: dict[str, Any] = {
        "access_token": "NEW",
        "token_type": "Bearer",
        "expires_in": 7200,
        "refresh_token": "REFRESH_2",
    }
    payload.update(overrides)
    return httpx.Response(200, json=payload)


def test_refreshes_expired_token_with_client_secret_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            "redirect_uris": [_REDIRECT_URI],
            "token_endpoint_auth_method": "client_secret_post",
        },
        MCPOAuthKeys.METADATA.value: {
            "issuer": "https://gitlab.example.com",
            "authorization_endpoint": "https://gitlab.example.com/oauth/authorize",
            "token_endpoint": _TOKEN_ENDPOINT,
        },
    }
    captured = _install_mocks(monkeypatch, config_data, response=_token_response())

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header == "Bearer NEW"
    sent_request = captured["sent_request"]
    assert str(sent_request.url) == _TOKEN_ENDPOINT
    body = parse_qs(sent_request.content.decode())
    assert body == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["REFRESH_1"],
        "client_id": ["cid"],
        "client_secret": ["csecret"],
    }
    assert "Authorization" not in sent_request.headers
    # Persisted via the real OnyxTokenStorage.set_tokens.
    persisted = captured["updated_config_data"]
    assert persisted[MCPOAuthKeys.TOKENS.value]["access_token"] == "NEW"
    assert persisted[MCPOAuthKeys.TOKENS.value]["refresh_token"] == "REFRESH_2"
    assert persisted["headers"]["Authorization"] == "Bearer NEW"
    assert persisted[MCPOAuthKeys.TOKEN_EXPIRES_AT.value] > time.time()


def test_refresh_uses_basic_auth_for_client_secret_basic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DCR can negotiate `client_secret_basic` (`_build_oauth_admin_config_data_for_update`);
    IdPs that require it reject a body-embedded secret. Exercises the real
    `OAuthContext.prepare_token_auth`, not a hand-rolled copy."""
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "client_secret": "csecret",
            "redirect_uris": [_REDIRECT_URI],
            "token_endpoint_auth_method": "client_secret_basic",
        },
        MCPOAuthKeys.METADATA.value: {
            "issuer": "https://gitlab.example.com",
            "authorization_endpoint": "https://gitlab.example.com/oauth/authorize",
            "token_endpoint": _TOKEN_ENDPOINT,
        },
    }
    captured = _install_mocks(monkeypatch, config_data, response=_token_response())

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header == "Bearer NEW"
    sent_request = captured["sent_request"]
    # client_secret must NOT be in the body, and Basic auth header must be set.
    body = parse_qs(sent_request.content.decode())
    assert body == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["REFRESH_1"],
        "client_id": ["cid"],
    }
    assert sent_request.headers["Authorization"] == "Basic Y2lkOmNzZWNyZXQ="


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
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "redirect_uris": [_REDIRECT_URI],
        },
    }
    captured = _install_mocks(monkeypatch, config_data, response=None)

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    # No network call is made, but the currently-persisted header is still
    # handed back (it may reflect a concurrent refresh from another call).
    assert header == "Bearer OLD"
    assert "sent_request" not in captured


def test_no_refresh_without_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {"access_token": "OLD", "token_type": "Bearer"},
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "redirect_uris": [_REDIRECT_URI],
        },
    }
    captured = _install_mocks(monkeypatch, config_data, response=None)

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header is None
    assert "sent_request" not in captured


def test_no_refresh_without_client_info(monkeypatch: pytest.MonkeyPatch) -> None:
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
    }
    captured = _install_mocks(monkeypatch, config_data, response=None)

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header is None
    assert "sent_request" not in captured


def test_no_refresh_without_persisted_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """No persisted `token_expires_at` reads as valid per `is_token_valid()` —
    left to manual reconnect rather than refreshed every call."""
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "redirect_uris": [_REDIRECT_URI],
        },
    }
    captured = _install_mocks(monkeypatch, config_data, response=None)

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header == "Bearer OLD"
    assert "sent_request" not in captured


def test_refresh_persists_via_real_onyx_token_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persists via the real `OnyxTokenStorage.set_tokens`, so `headers` is
    replaced with just the new `Authorization` value (not merged) — other
    static headers are dropped, same as a non-SSE refresh."""
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD", "X-Custom": "static-value"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "redirect_uris": [_REDIRECT_URI],
        },
        MCPOAuthKeys.METADATA.value: {
            "issuer": "https://gitlab.example.com",
            "authorization_endpoint": "https://gitlab.example.com/oauth/authorize",
            "token_endpoint": _TOKEN_ENDPOINT,
        },
    }
    _install_mocks(monkeypatch, config_data, response=_token_response())

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header == "Bearer NEW"
    assert config_data["headers"] == {"Authorization": "Bearer NEW"}


def test_refresh_failure_is_non_fatal_to_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-200 refresh response raises, and the caller (MCPTool.run) is
    expected to treat that as non-fatal and fall back to the stored token."""
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "redirect_uris": [_REDIRECT_URI],
        },
        MCPOAuthKeys.METADATA.value: {
            "issuer": "https://gitlab.example.com",
            "authorization_endpoint": "https://gitlab.example.com/oauth/authorize",
            "token_endpoint": _TOKEN_ENDPOINT,
        },
    }
    _install_mocks(monkeypatch, config_data, response=httpx.Response(401))

    with pytest.raises(RuntimeError):
        refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")
