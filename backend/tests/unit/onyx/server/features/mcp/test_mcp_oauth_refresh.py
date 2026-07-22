"""Regression coverage for SSE-transport MCP OAuth refresh: SSE can't use the
SDK's httpx.Auth refresh (open stream), so refresh_mcp_oauth_token_if_expired
drives OAuthClientProvider's refresh step directly instead.

Exercises the real OAuthClientProvider/OAuthContext/OnyxTokenStorage code —
client-auth-method branching, endpoint resolution, persistence — mocking only
the DB layer and the outbound network call.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlencode

import httpx
import pytest

import onyx.server.features.mcp.oauth as mcp_oauth
from onyx.cache.interface import CacheLockAcquisitionError
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


@contextmanager
def _noop_shared_lock(*_args: Any, **_kwargs: Any) -> Iterator[None]:
    """Stand-in for the real shared cache lock so these stay pure unit tests (no
    live Redis/Postgres). Single-flight coordination is covered elsewhere."""
    yield


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

    # Keep this a true unit test: no live cache backend for the single-flight lock.
    monkeypatch.setattr(mcp_oauth, "cache_shared_lock", _noop_shared_lock)
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
    monkeypatch.setattr(
        mcp_oauth,
        "mcp_ssrf_httpx_client_factory",
        lambda **_kwargs: fake_client,
    )
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


def _form_token_response(
    *, content_type: str | None = "application/x-www-form-urlencoded; charset=utf-8",
    **overrides: Any,
) -> httpx.Response:
    payload: dict[str, Any] = {
        "access_token": "NEW",
        "token_type": "bearer",
        "expires_in": 7200,
        "refresh_token": "REFRESH_2",
    }
    payload.update(overrides)
    headers = {} if content_type is None else {"content-type": content_type}
    return httpx.Response(200, content=urlencode(payload).encode(), headers=headers)


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


@pytest.mark.parametrize(
    "content_type",
    ["application/x-www-form-urlencoded; charset=utf-8", None, "application/json"],
)
def test_refreshes_form_encoded_token_response_with_rotated_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    content_type: str | None,
) -> None:
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "REFRESH_1",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
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
    captured = _install_mocks(
        monkeypatch,
        config_data,
        response=_form_token_response(content_type=content_type),
    )

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header == "Bearer NEW"
    persisted = captured["updated_config_data"]
    assert persisted[MCPOAuthKeys.TOKENS.value]["access_token"] == "NEW"
    assert persisted[MCPOAuthKeys.TOKENS.value]["refresh_token"] == "REFRESH_2"
    assert persisted["headers"]["Authorization"] == "Bearer NEW"
    assert persisted[MCPOAuthKeys.TOKEN_EXPIRES_AT.value] > time.time()
    assert any(
        record.getMessage() == "mcp_oauth.refresh.succeeded"
        for record in caplog.records
    )
    assert any(
        record.getMessage() == "mcp_oauth.refresh.persisted"
        for record in caplog.records
    )


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


def test_form_encoded_refresh_error_is_logged_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer OLD"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "OLD_ACCESS_TOKEN",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "ROTATING_REFRESH_TOKEN",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() - 60,
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "client_secret": "csecret",
            "redirect_uris": [_REDIRECT_URI],
            "token_endpoint_auth_method": "client_secret_post",
        },
        MCPOAuthKeys.METADATA.value: {
            "issuer": "https://github.example.com",
            "authorization_endpoint": "https://github.example.com/oauth/authorize",
            "token_endpoint": "https://github.example.com/oauth/token",
        },
    }
    response = httpx.Response(
        400,
        content=b"error=bad_refresh_token&error_description=refresh+token+expired",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    _install_mocks(monkeypatch, config_data, response=response)

    with pytest.raises(RuntimeError):
        refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    failed_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "mcp_oauth.refresh.failed"
    )
    started_record = next(
        record
        for record in caplog.records
        if record.getMessage() == "mcp_oauth.refresh.started"
    )
    assert getattr(failed_record, "oauth_error") == "bad_refresh_token"
    assert (
        getattr(failed_record, "response_content_type")
        == "application/x-www-form-urlencoded"
    )
    assert getattr(failed_record, "response_body_format") == "form"
    assert getattr(failed_record, "refresh_attempt_id") == getattr(
        started_record, "refresh_attempt_id"
    )
    assert "OLD_ACCESS_TOKEN" not in caplog.text
    assert "ROTATING_REFRESH_TOKEN" not in caplog.text
    assert "csecret" not in caplog.text


@pytest.mark.parametrize(
    ("expiry_offset_s", "expected_header"),
    [
        # Winner already persisted a fresh token: hand its header back.
        (3600, "Bearer PERSISTED"),
        # Winner still refreshing, so the stored token is expired and there is no
        # fresh header yet: return None. The caller (MCPTool.run) then falls back
        # to its existing header (which will 401 until the refresh lands).
        (-60, None),
    ],
)
def test_lock_contention_returns_persisted_header_or_none(
    monkeypatch: pytest.MonkeyPatch,
    expiry_offset_s: float,
    expected_header: str | None,
) -> None:
    """On lock contention we skip our own refresh and hand back whatever is
    persisted: the winner's fresh header if it has written one, else None when
    the stored token is still expired. Never a network call."""
    config_data: dict[str, Any] = {
        "headers": {"Authorization": "Bearer PERSISTED"},
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "PERSISTED",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "REFRESH_2",
        },
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: time.time() + expiry_offset_s,
        MCPOAuthKeys.CLIENT_INFO.value: {
            "client_id": "cid",
            "redirect_uris": [_REDIRECT_URI],
        },
    }
    captured = _install_mocks(monkeypatch, config_data, response=_token_response())

    @contextmanager
    def _contended_lock(*_args: Any, **_kwargs: Any) -> Iterator[None]:
        raise CacheLockAcquisitionError("held by a concurrent refresher")
        yield  # pragma: no cover — unreachable, satisfies the generator contract

    monkeypatch.setattr(mcp_oauth, "cache_shared_lock", _contended_lock)

    header = refresh_mcp_oauth_token_if_expired(_server_stub(), 42, "user-1")

    assert header == expected_header
    assert "sent_request" not in captured
