"""Unit tests for MCP per-user OAuth connect and callback paths."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.parse import parse_qs
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.exceptions import OAuthFlowError
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken
from pydantic import AnyUrl

from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api as mcp_api
from onyx.server.features.mcp.models import MCPOAuthKeys
from onyx.server.features.mcp.models import MCPUserOAuthConnectRequest

_RETURN_PATH = "/app/chat"
_AUTH_URL = "https://idp.example.com/oauth2/v1/authorize?state=test-state"
_CLIENT_INFO: dict[str, Any] = {
    "client_id": "test-client-id",
    "client_secret": "test-client-secret",
    "redirect_uris": [str(AnyUrl("http://localhost:3000/mcp/oauth/callback"))],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "client_secret_post",
}


def _make_user() -> User:
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "mcp-oauth-test@example.com"
    user.role = MagicMock()
    return user


def _make_mcp_server() -> MagicMock:
    server = MagicMock()
    server.id = 42
    server.name = "handshake-test-mcp"
    server.auth_type = MCPAuthenticationType.OAUTH
    server.transport = MCPTransport.STREAMABLE_HTTP
    server.server_url = "https://remote-mcp.example.com/mcp"
    server.admin_connection_config_id = 99
    server.admin_connection_config = MagicMock()
    return server


def _connection_data(*, with_tokens: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        MCPOAuthKeys.CLIENT_INFO.value: _CLIENT_INFO,
        "headers": {},
    }
    if with_tokens:
        data[MCPOAuthKeys.TOKENS.value] = {
            "access_token": "stored-access-token",
            "token_type": "Bearer",
        }
        data["headers"] = {"Authorization": "Bearer stored-access-token"}
    return data


class _FakeRedis:
    """Minimal Redis stub for connect/callback OAuth coordination."""

    def __init__(
        self,
        *,
        auth_url: str | None = None,
        block_seconds: float = 0.0,
        pkce_verifier: bytes | None = None,
        token_payload: str | None = None,
    ) -> None:
        self._auth_url = auth_url
        self._block_seconds = block_seconds
        self._pkce_verifier = pkce_verifier
        self._token_payload = token_payload
        self.blpop_calls = 0
        self.rpush_calls: list[tuple[str, str]] = []
        self._data: dict[str, bytes] = {}
        if pkce_verifier is not None:
            self._data["pkce"] = pkce_verifier

    def get(self, key: str) -> bytes | None:
        if key.endswith(":pkce_verifier"):
            return self._pkce_verifier
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self._data[key] = value.encode()
        if key.endswith(":pkce_verifier"):
            self._pkce_verifier = value.encode()
        return True

    def rpush(self, key: str, value: str) -> int:
        self.rpush_calls.append((key, value))
        if ":auth_url" in key:
            self._auth_url = value
        return 1

    def expire(self, key: str, ttl: int) -> bool:
        del key, ttl
        return True

    def blpop(self, keys: list[str], timeout: int) -> tuple[bytes, bytes] | None:
        del timeout
        self.blpop_calls += 1
        if self._block_seconds:
            time.sleep(self._block_seconds)
        key = keys[0]
        if ":tokens" in key and self._token_payload is not None:
            return (key.encode(), self._token_payload.encode())
        if self._auth_url is None:
            return None
        return (key.encode(), self._auth_url.encode())


class TestMergeUserOAuthConnectionConfig:
    def test_preserves_tokens_when_credentials_unchanged(self) -> None:
        existing: dict[str, Any] = {
            MCPOAuthKeys.TOKENS.value: {
                "access_token": "keep-me",
                "token_type": "Bearer",
            },
            "headers": {"Authorization": "Bearer keep-me"},
        }
        admin_seed: dict[str, Any] = {
            MCPOAuthKeys.CLIENT_INFO.value: _CLIENT_INFO,
            "headers": {},
        }
        merged = mcp_api._merge_user_oauth_connection_config(
            existing,
            admin_seed,
            credentials_changed=False,
        )
        assert merged[MCPOAuthKeys.TOKENS.value] == existing[MCPOAuthKeys.TOKENS.value]
        assert merged["headers"] == existing["headers"]

    def test_clears_tokens_when_credentials_changed(self) -> None:
        existing: dict[str, Any] = {
            MCPOAuthKeys.TOKENS.value: {"access_token": "drop-me", "token_type": "Bearer"},
            "headers": {"Authorization": "Bearer drop-me"},
        }
        admin_seed: dict[str, Any] = {MCPOAuthKeys.CLIENT_INFO.value: _CLIENT_INFO}
        merged = mcp_api._merge_user_oauth_connection_config(
            existing,
            admin_seed,
            credentials_changed=True,
        )
        assert MCPOAuthKeys.TOKENS.value not in merged


class TestConnectionHasOAuthTokens:
    def test_false_when_no_tokens_key(self) -> None:
        assert not mcp_api._connection_has_oauth_tokens({"client_info": {"client_id": "x"}})

    def test_false_when_tokens_empty(self) -> None:
        assert not mcp_api._connection_has_oauth_tokens({MCPOAuthKeys.TOKENS.value: None})

    def test_true_when_tokens_present(self) -> None:
        assert mcp_api._connection_has_oauth_tokens(
            {
                MCPOAuthKeys.TOKENS.value: {
                    "access_token": "at",
                    "token_type": "Bearer",
                }
            }
        )

    def test_headers_without_tokens_is_not_authenticated(self) -> None:
        """Regression: stored client_info/headers must not imply stored user tokens."""
        assert not mcp_api._connection_has_oauth_tokens(
            {
                MCPOAuthKeys.CLIENT_INFO.value: {"client_id": "id"},
                "headers": {},
            }
        )


@pytest.mark.asyncio
async def test_token_storage_preserves_refresh_token_when_refresh_response_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OAuth refresh responses may omit refresh_token; keep the stored one."""
    config = MagicMock()
    config.id = 100
    config_data: dict[str, Any] = {
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "old-access-token",
            "refresh_token": "keep-refresh-token",
            "token_type": "Bearer",
        }
    }
    updated_config_data: dict[str, Any] = {}

    class _FakeSession:
        def __enter__(self) -> MagicMock:
            return MagicMock()

        def __exit__(self, *_args: object) -> None:
            return None

    def _update_connection_config(
        _config_id: int, _db_session: MagicMock, new_config_data: dict[str, Any]
    ) -> None:
        updated_config_data.update(new_config_data)

    monkeypatch.setattr(mcp_api, "get_session_with_current_tenant", _FakeSession)
    monkeypatch.setattr(mcp_api, "get_connection_config_by_id", lambda *_a: config)
    monkeypatch.setattr(mcp_api, "extract_connection_data", lambda *_a: config_data)
    monkeypatch.setattr(mcp_api, "update_connection_config", _update_connection_config)
    monkeypatch.setattr(mcp_api.time, "time", lambda: 1000.0)

    await mcp_api.OnyxTokenStorage(config.id).set_tokens(
        OAuthToken(
            access_token="new-access-token",
            token_type="Bearer",
            expires_in=3600,
        )
    )

    stored_tokens = updated_config_data[MCPOAuthKeys.TOKENS.value]
    assert stored_tokens["access_token"] == "new-access-token"
    assert stored_tokens["refresh_token"] == "keep-refresh-token"
    assert stored_tokens[mcp_api.TOKEN_EXPIRES_AT] == 4600.0
    assert updated_config_data["headers"] == {
        "Authorization": "Bearer new-access-token"
    }


@pytest.mark.asyncio
async def test_token_storage_treats_legacy_refresh_tokens_as_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = MagicMock()
    config.id = 100
    config_data: dict[str, Any] = {
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "legacy-access-token",
            "refresh_token": "legacy-refresh-token",
            "token_type": "Bearer",
        }
    }

    class _FakeSession:
        def __enter__(self) -> MagicMock:
            return MagicMock()

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(mcp_api, "get_session_with_current_tenant", _FakeSession)
    monkeypatch.setattr(mcp_api, "get_connection_config_by_id", lambda *_a: config)
    monkeypatch.setattr(mcp_api, "extract_connection_data", lambda *_a: config_data)

    assert await mcp_api.OnyxTokenStorage(config.id).get_token_expiry_time() == 1.0


def test_oauth_config_persists_explicit_authorization_params() -> None:
    config_data = mcp_api._build_oauth_admin_config_data(
        client_id="test-client-id",
        client_secret="test-client-secret",
        authorization_url_params={"access_type": "offline", "prompt": "consent"},
    )

    assert config_data[MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value] == {
        "access_type": "offline",
        "prompt": "consent",
    }


def test_non_google_oauth_config_has_no_extra_authorization_params() -> None:
    config_data = mcp_api._build_oauth_admin_config_data(
        client_id="test-client-id",
        client_secret="test-client-secret",
    )

    assert MCPOAuthKeys.AUTHORIZATION_URL_PARAMS.value not in config_data


@pytest.mark.asyncio
async def test_oauth_provider_hydrates_stored_token_expiry(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
) -> None:
    async def _get_tokens(_storage: mcp_api.OnyxTokenStorage) -> OAuthToken:
        return OAuthToken(access_token="stored-access-token", token_type="Bearer")

    async def _get_client_info(
        _storage: mcp_api.OnyxTokenStorage,
    ) -> OAuthClientInformationFull:
        return OAuthClientInformationFull.model_validate(_CLIENT_INFO)

    async def _get_token_expiry_time(_storage: mcp_api.OnyxTokenStorage) -> float:
        return 1234.0

    async def _get_oauth_metadata_context(
        _storage: mcp_api.OnyxTokenStorage,
    ) -> None:
        return None

    monkeypatch.setattr(mcp_api.OnyxTokenStorage, "get_tokens", _get_tokens)
    monkeypatch.setattr(mcp_api.OnyxTokenStorage, "get_client_info", _get_client_info)
    monkeypatch.setattr(
        mcp_api.OnyxTokenStorage,
        "get_token_expiry_time",
        _get_token_expiry_time,
    )
    monkeypatch.setattr(
        mcp_api.OnyxTokenStorage,
        "get_oauth_metadata_context",
        _get_oauth_metadata_context,
    )

    provider = mcp_api.make_oauth_provider(
        mcp_server=mcp_server,
        user_id="test-user-id",
        return_path=_RETURN_PATH,
        connection_config_id=100,
        admin_config_id=99,
    )

    await provider._initialize()

    assert provider.context.token_expiry_time == 1234.0


@pytest.mark.asyncio
async def test_oauth_provider_hydrates_stored_oauth_metadata(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
) -> None:
    async def _get_tokens(_storage: mcp_api.OnyxTokenStorage) -> OAuthToken:
        return OAuthToken(access_token="stored-access-token", token_type="Bearer")

    async def _get_client_info(
        _storage: mcp_api.OnyxTokenStorage,
    ) -> OAuthClientInformationFull:
        return OAuthClientInformationFull.model_validate(_CLIENT_INFO)

    async def _get_token_expiry_time(
        _storage: mcp_api.OnyxTokenStorage,
    ) -> None:
        return None

    async def _get_oauth_metadata_context(
        _storage: mcp_api.OnyxTokenStorage,
    ) -> dict[str, object]:
        return {
            "auth_server_url": "https://accounts.google.com",
            "oauth_metadata": {
                "issuer": "https://accounts.google.com",
                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_endpoint": "https://oauth2.googleapis.com/token",
            },
            "protected_resource_metadata": {
                "resource": "https://logging.googleapis.com/mcp",
                "authorization_servers": ["https://accounts.google.com"],
            },
        }

    monkeypatch.setattr(mcp_api.OnyxTokenStorage, "get_tokens", _get_tokens)
    monkeypatch.setattr(mcp_api.OnyxTokenStorage, "get_client_info", _get_client_info)
    monkeypatch.setattr(
        mcp_api.OnyxTokenStorage,
        "get_token_expiry_time",
        _get_token_expiry_time,
    )
    monkeypatch.setattr(
        mcp_api.OnyxTokenStorage,
        "get_oauth_metadata_context",
        _get_oauth_metadata_context,
    )

    provider = mcp_api.make_oauth_provider(
        mcp_server=mcp_server,
        user_id="test-user-id",
        return_path=_RETURN_PATH,
        connection_config_id=100,
        admin_config_id=99,
    )

    await provider._initialize()

    assert provider.context.auth_server_url == "https://accounts.google.com"
    assert str(provider.context.oauth_metadata.token_endpoint) == (
        "https://oauth2.googleapis.com/token"
    )
    assert provider.context.protected_resource_metadata is not None


@pytest.mark.asyncio
async def test_publish_oauth_authorization_url_includes_extra_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_url: str | None = None

    async def _redirect_handler(auth_url: str) -> None:
        nonlocal captured_url
        captured_url = auth_url

    async def _get_authorization_url_params(
        _storage: mcp_api.OnyxTokenStorage,
    ) -> dict[str, str]:
        return {"access_type": "offline", "prompt": "consent"}

    monkeypatch.setattr(
        mcp_api.OnyxTokenStorage,
        "get_authorization_url_params",
        _get_authorization_url_params,
    )
    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: _FakeRedis())

    provider = mcp_api.OnyxOAuthClientProvider(
        server_url="https://remote-mcp.example.com/mcp",
        client_metadata=mcp_api.OAuthClientMetadata(
            client_name="Onyx - test",
            redirect_uris=[AnyUrl("http://localhost:3000/mcp/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=mcp_api.OnyxTokenStorage(100),
        redirect_handler=_redirect_handler,
        callback_handler=None,
    )
    provider.context.client_info = OAuthClientInformationFull.model_validate(
        _CLIENT_INFO
    )

    await mcp_api._publish_oauth_authorization_url(provider, "test-user-id")

    assert captured_url is not None
    query = parse_qs(urlparse(captured_url).query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]


@pytest.fixture
def mcp_server() -> MagicMock:
    return _make_mcp_server()


@pytest.fixture
def user() -> User:
    return _make_user()


@pytest.fixture
def connection_config() -> MagicMock:
    config = MagicMock()
    config.id = 100
    return config


def _patch_connect_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    *,
    mcp_server: MagicMock,
    connection_config: MagicMock,
    connection_data: dict[str, Any],
    fake_redis: _FakeRedis,
    init_delay: float = 0.0,
) -> tuple[AsyncMock, AsyncMock]:
    """Patch DB/Redis/MCP client calls used by ``_connect_oauth``."""

    monkeypatch.setattr(mcp_api, "get_mcp_server_by_id", lambda *_a, **_k: mcp_server)
    monkeypatch.setattr(
        mcp_api, "get_user_connection_config", lambda *_a, **_k: connection_config
    )
    monkeypatch.setattr(
        mcp_api,
        "extract_connection_data",
        lambda *_a, **_k: dict(connection_data),
    )
    monkeypatch.setattr(mcp_api, "create_connection_config", lambda **_k: connection_config)
    monkeypatch.setattr(mcp_api, "update_connection_config", lambda *_a, **_k: None)
    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: fake_redis)

    proactive_oauth = AsyncMock()
    monkeypatch.setattr(mcp_api, "_start_proactive_user_oauth", proactive_oauth)

    initialize_mock = AsyncMock(return_value=MagicMock())

    async def slow_initialize(*_args: object, **kwargs: object) -> MagicMock:
        if init_delay:
            await asyncio.sleep(init_delay)
        return await initialize_mock(*_args, **kwargs)

    monkeypatch.setattr(mcp_api, "initialize_mcp_client", slow_initialize)
    monkeypatch.setattr(
        mcp_api,
        "make_oauth_provider",
        lambda *_a, **_k: MagicMock(),
    )
    return proactive_oauth, initialize_mock


@pytest.mark.asyncio
async def test_connect_oauth_returns_idp_url_when_initialize_finishes_first(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    """Regression: handshake RPC success must not short-circuit to ``return_path``."""
    fake_redis = _FakeRedis(auth_url=_AUTH_URL, block_seconds=0.05)

    async def _publish_auth_url(*_args: object, **_kwargs: object) -> None:
        fake_redis.rpush(mcp_api.key_auth_url(str(user.id)), _AUTH_URL)

    proactive_oauth, _initialize_mock = _patch_connect_dependencies(
        monkeypatch,
        mcp_server=mcp_server,
        connection_config=connection_config,
        connection_data=_connection_data(with_tokens=False),
        fake_redis=fake_redis,
        init_delay=0.0,
    )
    proactive_oauth.side_effect = _publish_auth_url

    request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
        oauth_client_id="test-client-id",
        oauth_client_secret="test-client-secret",
        oauth_client_id_changed=True,
        oauth_client_secret_changed=True,
    )

    response = await mcp_api._connect_oauth(
        request, MagicMock(), is_admin=False, user=user
    )

    assert response.oauth_url == _AUTH_URL
    assert response.oauth_url != _RETURN_PATH
    proactive_oauth.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_oauth_without_tokens_skips_initialize_mcp_client_on_proactive_success(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    """Proactive connect must not call ``initialize_mcp_client`` (SDK 401 path)."""
    fake_redis = _FakeRedis(auth_url=_AUTH_URL)

    async def _publish_auth_url(*_args: object, **_kwargs: object) -> None:
        fake_redis.rpush(mcp_api.key_auth_url(str(user.id)), _AUTH_URL)

    proactive_oauth, initialize_mock = _patch_connect_dependencies(
        monkeypatch,
        mcp_server=mcp_server,
        connection_config=connection_config,
        connection_data=_connection_data(with_tokens=False),
        fake_redis=fake_redis,
    )
    proactive_oauth.side_effect = _publish_auth_url

    request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
        oauth_client_id="test-client-id",
        oauth_client_secret="test-client-secret",
        oauth_client_id_changed=True,
        oauth_client_secret_changed=True,
    )

    await mcp_api._connect_oauth(request, MagicMock(), is_admin=False, user=user)

    initialize_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_oauth_returns_return_path_when_tokens_already_stored(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    fake_redis = _FakeRedis(auth_url=_AUTH_URL)
    proactive_oauth, initialize_mock = _patch_connect_dependencies(
        monkeypatch,
        mcp_server=mcp_server,
        connection_config=connection_config,
        connection_data=_connection_data(with_tokens=True),
        fake_redis=fake_redis,
    )

    request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
    )

    response = await mcp_api._connect_oauth(
        request, MagicMock(), is_admin=False, user=user
    )

    assert response.oauth_url == _RETURN_PATH
    proactive_oauth.assert_not_awaited()
    assert fake_redis.blpop_calls == 0
    assert initialize_mock.await_args is not None
    assert initialize_mock.await_args.kwargs.get("auth") is not None


@pytest.mark.asyncio
async def test_await_sdk_oauth_auth_url_leaves_init_task_running_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK fallback must keep initialize alive so legacy callback can finish OAuth."""
    init_started = asyncio.Event()
    init_cancelled = False

    async def _blocking_initialize(*_args: object, **_kwargs: object) -> MagicMock:
        init_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            nonlocal init_cancelled
            init_cancelled = True
            raise
        return MagicMock()

    monkeypatch.setattr(mcp_api, "initialize_mcp_client", _blocking_initialize)
    monkeypatch.setattr(mcp_api, "_set_oauth_flow_mode", lambda *_a, **_k: None)
    fake_redis = _FakeRedis(auth_url=_AUTH_URL)
    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: fake_redis)

    oauth_url = await mcp_api._await_sdk_oauth_auth_url(
        probe_url="https://mcp.example.com/mcp",
        connection_headers={},
        transport=MCPTransport.STREAMABLE_HTTP,
        oauth_auth=MagicMock(),
        user_id="user-1",
    )

    assert oauth_url == _AUTH_URL
    assert init_started.is_set()
    assert not init_cancelled


@pytest.mark.asyncio
async def test_connect_oauth_sdk_fallback_when_proactive_fails(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    """Proactive failure must trigger SDK fallback."""
    fake_redis = _FakeRedis(auth_url=None)
    sdk_fallback = AsyncMock(return_value=_AUTH_URL)

    async def _slow_failing_proactive(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0.05)
        raise OAuthFlowError("discovery failed")

    monkeypatch.setattr(mcp_api, "get_mcp_server_by_id", lambda *_a, **_k: mcp_server)
    monkeypatch.setattr(
        mcp_api, "get_user_connection_config", lambda *_a, **_k: connection_config
    )
    monkeypatch.setattr(
        mcp_api,
        "extract_connection_data",
        lambda *_a, **_k: _connection_data(with_tokens=False),
    )
    monkeypatch.setattr(mcp_api, "create_connection_config", lambda **_k: connection_config)
    monkeypatch.setattr(mcp_api, "update_connection_config", lambda *_a, **_k: None)
    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(mcp_api, "_start_proactive_user_oauth", _slow_failing_proactive)
    monkeypatch.setattr(mcp_api, "_await_sdk_oauth_auth_url", sdk_fallback)
    monkeypatch.setattr(
        mcp_api,
        "make_oauth_provider",
        lambda *_a, **_k: MagicMock(),
    )

    request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
        oauth_client_id="test-client-id",
        oauth_client_secret="test-client-secret",
        oauth_client_id_changed=True,
        oauth_client_secret_changed=True,
    )

    response = await mcp_api._connect_oauth(
        request, MagicMock(), is_admin=False, user=user
    )

    assert response.oauth_url == _AUTH_URL
    sdk_fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_oauth_errors_instead_of_silent_refresh_when_no_tokens(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    monkeypatch.setattr(mcp_api, "OAUTH_WAIT_SECONDS", 1)
    fake_redis = _FakeRedis(auth_url=None)
    proactive_oauth, _initialize_mock = _patch_connect_dependencies(
        monkeypatch,
        mcp_server=mcp_server,
        connection_config=connection_config,
        connection_data=_connection_data(with_tokens=False),
        fake_redis=fake_redis,
    )
    proactive_oauth.side_effect = OAuthFlowError("discovery failed")

    async def _sdk_fallback_fail(**_kwargs: object) -> str:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Failed to start OAuth authorization: discovery failed",
        )

    monkeypatch.setattr(mcp_api, "_await_sdk_oauth_auth_url", _sdk_fallback_fail)

    request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
        oauth_client_id="test-client-id",
        oauth_client_secret="test-client-secret",
        oauth_client_id_changed=True,
        oauth_client_secret_changed=True,
    )

    with pytest.raises(OnyxError) as exc_info:
        await mcp_api._connect_oauth(request, MagicMock(), is_admin=False, user=user)

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert (
        "Could not start OAuth authorization" in detail
        or "Auth URL retrieval timed out" in detail
        or "Failed to start OAuth authorization" in detail
    )


@pytest.mark.asyncio
async def test_connect_oauth_preserves_existing_tokens_in_user_config_update(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    """Regression: merging admin client_info must not wipe stored user OAuth tokens."""
    existing = _connection_data(with_tokens=True)
    updated_configs: list[dict[str, Any]] = []

    def _capture_update(
        _config_id: int, _db: MagicMock, config_data: dict[str, Any]
    ) -> None:
        updated_configs.append(dict(config_data))

    monkeypatch.setattr(mcp_api, "get_mcp_server_by_id", lambda *_a, **_k: mcp_server)
    monkeypatch.setattr(
        mcp_api, "get_user_connection_config", lambda *_a, **_k: connection_config
    )

    extract_calls = 0

    def _extract(_config: MagicMock, **kwargs: object) -> dict[str, Any]:
        del _config, kwargs
        nonlocal extract_calls
        extract_calls += 1
        return dict(existing)

    monkeypatch.setattr(mcp_api, "extract_connection_data", _extract)
    monkeypatch.setattr(mcp_api, "update_connection_config", _capture_update)
    monkeypatch.setattr(mcp_api, "create_connection_config", lambda **_k: connection_config)
    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(mcp_api, "_start_proactive_user_oauth", AsyncMock())
    monkeypatch.setattr(
        mcp_api,
        "initialize_mcp_client",
        AsyncMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        mcp_api,
        "make_oauth_provider",
        lambda *_a, **_k: MagicMock(),
    )

    request = MCPUserOAuthConnectRequest(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        include_resource_param=True,
        oauth_client_id="test-client-id",
        oauth_client_secret="test-client-secret",
        oauth_client_id_changed=False,
        oauth_client_secret_changed=False,
    )

    response = await mcp_api._connect_oauth(
        request, MagicMock(), is_admin=False, user=user
    )

    assert response.oauth_url == _RETURN_PATH
    assert len(updated_configs) == 1
    assert updated_configs[0][MCPOAuthKeys.TOKENS.value] == existing[
        MCPOAuthKeys.TOKENS.value
    ]
    assert updated_configs[0]["headers"] == existing["headers"]


@pytest.mark.asyncio
async def test_ensure_oauth_client_registered_performs_dcr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    provider.context.client_info = None
    provider.context.oauth_metadata = MagicMock()
    provider.context.client_metadata = MagicMock()
    provider.context.client_metadata_url = None
    provider.context.get_authorization_base_url.return_value = "https://idp.example.com"
    provider._initialize = AsyncMock()

    registered = OAuthClientInformationFull(
        client_id="dcr-client-id",
        redirect_uris=[AnyUrl("http://localhost:3000/mcp/oauth/callback")],
        grant_types=["authorization_code"],
        response_types=["code"],
    )
    storage = MagicMock()
    storage.set_client_info = AsyncMock()
    provider.context.storage = storage

    reg_response = MagicMock()
    monkeypatch.setattr(
        mcp_api,
        "create_client_registration_request",
        lambda *_a, **_k: MagicMock(),
    )
    monkeypatch.setattr(
        mcp_api,
        "should_use_client_metadata_url",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        mcp_api,
        "handle_registration_response",
        AsyncMock(return_value=registered),
    )

    class _FakeHttpx:
        async def __aenter__(self) -> "_FakeHttpx":
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def send(self, _req: object) -> MagicMock:
            return reg_response

    monkeypatch.setattr(mcp_api.httpx, "AsyncClient", lambda: _FakeHttpx())

    await mcp_api._ensure_oauth_client_registered(provider)

    storage.set_client_info.assert_awaited_once()
    assert provider.context.client_info == registered


@pytest.mark.asyncio
async def test_process_oauth_callback_uses_legacy_sdk_path_without_pkce_verifier(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    """Preserve HTTP-401 + SDK OAuth servers that never set proactive PKCE state."""
    user_id = str(user.id)
    state = "legacy-state"
    token_json = json.dumps(
        {"access_token": "legacy-access", "token_type": "Bearer"},
    )
    fake_redis = _FakeRedis(token_payload=token_json)

    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(mcp_api, "get_mcp_server_by_id", lambda *_a, **_k: mcp_server)
    monkeypatch.setattr(
        mcp_api, "get_user_connection_config", lambda *_a, **_k: connection_config
    )
    monkeypatch.setattr(
        mcp_api,
        "key_state",
        lambda _uid: "state-key",
    )
    monkeypatch.setattr(
        mcp_api,
        "key_pkce_verifier",
        lambda _uid: f"mcp:oauth:{user_id}:pkce_verifier",
    )
    monkeypatch.setattr(
        mcp_api,
        "key_oauth_flow_mode",
        lambda _uid: f"mcp:oauth:{user_id}:flow_mode",
    )
    monkeypatch.setattr(
        mcp_api,
        "_oauth_callback_uses_proactive_exchange",
        lambda _uid: False,
    )

    state_obj = mcp_api.MCPOauthState(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        is_admin=False,
        state=state,
    )
    fake_redis._data["state-key"] = state_obj.model_dump_json().encode()

    request = MagicMock()
    request.query_params = {"state": state, "code": "legacy-code"}

    with patch.object(mcp_api, "_complete_oauth_token_exchange_from_callback", AsyncMock()) as proactive_exchange:
        response = await mcp_api.process_oauth_callback(
            request, MagicMock(), user=user
        )

    proactive_exchange.assert_not_awaited()
    assert any(":codes" in key for key, _ in fake_redis.rpush_calls)
    assert fake_redis.blpop_calls == 1
    assert response.success is True


@pytest.mark.asyncio
async def test_process_oauth_callback_uses_proactive_path_by_flow_mode(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
    connection_config: MagicMock,
) -> None:
    user_id = str(user.id)
    state = "proactive-state"
    fake_redis = _FakeRedis()
    fake_redis._data[f"mcp:oauth:{user_id}:flow_mode"] = (
        mcp_api.OAUTH_FLOW_MODE_PROACTIVE.encode()
    )

    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(mcp_api, "get_mcp_server_by_id", lambda *_a, **_k: mcp_server)
    monkeypatch.setattr(
        mcp_api, "get_user_connection_config", lambda *_a, **_k: connection_config
    )
    monkeypatch.setattr(mcp_api, "key_state", lambda _uid: "state-key")

    state_obj = mcp_api.MCPOauthState(
        server_id=mcp_server.id,
        return_path=_RETURN_PATH,
        is_admin=False,
        state=state,
    )
    fake_redis._data["state-key"] = state_obj.model_dump_json().encode()

    request = MagicMock()
    request.query_params = {"state": state, "code": "proactive-code"}

    with patch.object(
        mcp_api, "_complete_oauth_callback_legacy_sdk_path", AsyncMock()
    ) as legacy_path:
        with patch.object(
            mcp_api,
            "_complete_oauth_token_exchange_from_callback",
            AsyncMock(),
        ) as proactive_exchange:
            await mcp_api.process_oauth_callback(
                request, MagicMock(), user=user
            )

    proactive_exchange.assert_awaited_once()
    legacy_path.assert_not_awaited()


@pytest.mark.asyncio
async def test_redirect_handler_persists_state_before_auth_url(
    monkeypatch: pytest.MonkeyPatch,
    mcp_server: MagicMock,
    user: User,
) -> None:
    """Callback state must exist before the connect waiter can consume the auth URL."""
    redis_ops: list[tuple[str, str]] = []

    class _OrderTrackingRedis:
        def set(self, key: str, value: str, ex: int | None = None) -> bool:
            del value, ex
            redis_ops.append(("set", key))
            return True

        def rpush(self, key: str, value: str) -> int:
            del value
            redis_ops.append(("rpush", key))
            return 1

        def expire(self, key: str, ttl: int) -> bool:
            del key, ttl
            return True

    monkeypatch.setattr(mcp_api, "get_redis_client", lambda: _OrderTrackingRedis())
    user_id = str(user.id)
    provider = mcp_api.make_oauth_provider(
        mcp_server,
        user_id,
        _RETURN_PATH,
        connection_config_id=100,
        admin_config_id=mcp_server.admin_connection_config_id,
    )

    await provider.context.redirect_handler(_AUTH_URL)

    state_key = mcp_api.key_state(user_id)
    auth_url_key = mcp_api.key_auth_url(user_id)
    state_op_index = next(
        i for i, (op, key) in enumerate(redis_ops) if op == "set" and key == state_key
    )
    auth_url_op_index = next(
        i
        for i, (op, key) in enumerate(redis_ops)
        if op == "rpush" and key == auth_url_key
    )
    assert state_op_index < auth_url_op_index


@pytest.mark.asyncio
async def test_connect_oauth_without_tokens_awaits_publisher_after_auth_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not cancel the publisher after returning a user-visible auth URL."""
    created_tasks: list[asyncio.Task[object]] = []
    real_create_task = asyncio.create_task

    def _tracking_create_task(coro: object) -> asyncio.Task[object]:
        task = real_create_task(coro)  # type: ignore[arg-type]
        created_tasks.append(task)
        return task

    async def _slow_publish(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(0.08)

    async def _immediate_auth_url(
        _user_id: str, _publish_task: asyncio.Task[None]
    ) -> str:
        return _AUTH_URL

    monkeypatch.setattr(asyncio, "create_task", _tracking_create_task)
    monkeypatch.setattr(mcp_api, "_start_proactive_user_oauth", _slow_publish)
    monkeypatch.setattr(
        mcp_api, "_await_oauth_auth_url_for_connect", _immediate_auth_url
    )
    monkeypatch.setattr(mcp_api, "make_oauth_provider", lambda *_a, **_k: MagicMock())

    oauth_url = await mcp_api._connect_oauth_without_tokens(
        oauth_auth=MagicMock(),
        probe_url="https://mcp.example.com/mcp",
        connection_headers={},
        transport=MCPTransport.STREAMABLE_HTTP,
        user_id="user-1",
        mcp_server_name="test-server",
    )

    assert oauth_url == _AUTH_URL
    publish_task = created_tasks[0]
    assert not publish_task.cancelled()
    assert publish_task.done()


@pytest.mark.asyncio
async def test_connect_oauth_without_tokens_cancels_publisher_on_auth_url_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not leave the publisher running after auth URL retrieval fails."""
    created_tasks: list[asyncio.Task[object]] = []
    real_create_task = asyncio.create_task
    publish_cancelled = asyncio.Event()

    def _tracking_create_task(coro: object) -> asyncio.Task[object]:
        task = real_create_task(coro)  # type: ignore[arg-type]
        created_tasks.append(task)
        return task

    async def _slow_publish(*_args: object, **_kwargs: object) -> None:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            publish_cancelled.set()
            raise

    async def _failing_auth_url(
        _user_id: str, _publish_task: asyncio.Task[None]
    ) -> str:
        await asyncio.sleep(0)
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Auth URL retrieval timed out")

    monkeypatch.setattr(asyncio, "create_task", _tracking_create_task)
    monkeypatch.setattr(mcp_api, "_start_proactive_user_oauth", _slow_publish)
    monkeypatch.setattr(
        mcp_api, "_await_oauth_auth_url_for_connect", _failing_auth_url
    )
    monkeypatch.setattr(mcp_api, "make_oauth_provider", lambda *_a, **_k: MagicMock())

    with pytest.raises(OnyxError, match="Auth URL retrieval timed out"):
        await mcp_api._connect_oauth_without_tokens(
            oauth_auth=MagicMock(),
            probe_url="https://mcp.example.com/mcp",
            connection_headers={},
            transport=MCPTransport.STREAMABLE_HTTP,
            user_id="user-1",
            mcp_server_name="test-server",
        )

    publish_task = created_tasks[0]
    assert publish_task.cancelled()
    assert publish_cancelled.is_set()


_MCP_SDK_OAUTH_PROVIDER_INTERNALS = (
    "_initialize",
    "_exchange_token_authorization_code",
    "_handle_token_response",
)


def test_mcp_sdk_oauth_provider_exposes_proactive_callback_internals() -> None:
    """Fail on MCP SDK upgrades that rename private methods used by proactive OAuth."""
    for method_name in _MCP_SDK_OAUTH_PROVIDER_INTERNALS:
        assert hasattr(OAuthClientProvider, method_name), (
            f"OAuthClientProvider.{method_name} missing; "
            "proactive OAuth callback may need updating for this mcp version"
        )
        assert callable(getattr(OAuthClientProvider, method_name))
