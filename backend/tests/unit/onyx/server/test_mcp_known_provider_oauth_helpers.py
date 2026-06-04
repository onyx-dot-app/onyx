import asyncio
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast
from typing import Iterator
from urllib.parse import parse_qs
from urllib.parse import urlparse

import pytest
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthToken

import onyx.server.features.mcp.api as mcp_api
from onyx.auth.oauth_token_manager import build_oauth_authorization_url
from onyx.auth.oauth_token_manager import exchange_oauth_code_for_token
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.models import MCPServer as DbMCPServer
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp.api import _absolute_token_expiry
from onyx.server.features.mcp.api import _known_provider_oauth_metadata
from onyx.server.features.mcp.api import _mcp_known_provider_flow_params
from onyx.server.features.mcp.api import _token_dict_with_preserved_refresh
from onyx.server.features.mcp.api import make_oauth_provider
from onyx.server.features.mcp.models import MCPOAuthKeys


def _make_mcp_server_stub(
    *,
    auth_endpoint: str | None = "https://accounts.example.com/oauth/authorize",
    token_endpoint: str | None = "https://accounts.example.com/oauth/token",
    scopes: list[str] | None = None,
    params: dict[str, str] | None = None,
    provider_mode: MCPOAuthProviderMode = MCPOAuthProviderMode.KNOWN_PROVIDER,
) -> DbMCPServer:
    return cast(
        DbMCPServer,
        SimpleNamespace(
            oauth_authorization_endpoint=auth_endpoint,
            oauth_token_endpoint=token_endpoint,
            oauth_scopes_override=scopes,
            oauth_additional_auth_params=params,
            oauth_provider_mode=provider_mode,
            server_url="https://mcp.example.com/mcp",
            name="Example MCP",
            id=1,
        ),
    )


def _make_client_info_stub(
    *, client_id: str | None = "client-123", client_secret: str | None = "secret-123"
) -> OAuthClientInformationFull:
    return cast(
        OAuthClientInformationFull,
        SimpleNamespace(client_id=client_id, client_secret=client_secret),
    )


def test_known_provider_flow_params_maps_server_and_client_fields() -> None:
    params = _mcp_known_provider_flow_params(
        _make_mcp_server_stub(
            scopes=["scope.one", "scope.two"], params={"access_type": "offline"}
        ),
        _make_client_info_stub(),
    )
    assert params.authorization_url == "https://accounts.example.com/oauth/authorize"
    assert params.token_url == "https://accounts.example.com/oauth/token"
    assert params.client_id == "client-123"
    assert params.client_secret == "secret-123"
    assert params.scopes == ["scope.one", "scope.two"]
    assert params.additional_params == {"access_type": "offline"}


def test_known_provider_oauth_url_includes_required_and_optional_params() -> None:
    oauth_url = build_oauth_authorization_url(
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(
                scopes=["scope.one", "scope.two"], params={"access_type": "offline"}
            ),
            _make_client_info_stub(),
        ),
        redirect_uri="https://onyx.example.com/mcp/oauth/callback",
        state="state-123",
        code_challenge="challenge-456",
        resource="https://mcp.example.com/mcp",
    )
    query = parse_qs(urlparse(oauth_url).query)
    assert query["client_id"] == ["client-123"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-123"]
    assert query["code_challenge"] == ["challenge-456"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["scope.one scope.two"]
    assert query["resource"] == ["https://mcp.example.com/mcp"]
    assert query["access_type"] == ["offline"]


def test_known_provider_flow_params_requires_endpoints() -> None:
    with pytest.raises(OnyxError, match="oauth_authorization_endpoint"):
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(auth_endpoint=None), _make_client_info_stub()
        )


def test_known_provider_flow_params_requires_client_id() -> None:
    with pytest.raises(OnyxError, match="client_id"):
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(), _make_client_info_stub(client_id=None)
        )


def test_known_provider_code_exchange_sends_code_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, dict[str, str]] = {}

    class _Response:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, str | int]:
            return {
                "access_token": "token-abc",
                "token_type": "Bearer",
                "refresh_token": "refresh-abc",
                "expires_in": 3600,
            }

    def _fake_post(url: str, data: dict[str, str], **kwargs: object) -> _Response:
        del url, kwargs
        captured["data"] = data
        return _Response()

    monkeypatch.setattr("onyx.auth.oauth_token_manager.requests.post", _fake_post)

    token_payload = exchange_oauth_code_for_token(
        _mcp_known_provider_flow_params(
            _make_mcp_server_stub(), _make_client_info_stub()
        ),
        code="auth-code-123",
        redirect_uri="https://onyx.example.com/mcp/oauth/callback",
        code_verifier="verifier-123",
    )
    assert token_payload["access_token"] == "token-abc"
    assert "expires_at" in token_payload
    assert captured["data"]["code_verifier"] == "verifier-123"
    assert captured["data"]["client_secret"] == "secret-123"


def test_known_provider_oauth_metadata_uses_configured_token_endpoint() -> None:
    metadata = _known_provider_oauth_metadata(
        _make_mcp_server_stub(provider_mode=MCPOAuthProviderMode.KNOWN_PROVIDER)
    )
    assert metadata is not None
    # The whole point: refresh must hit the configured endpoint, not the SDK's
    # `<server-origin>/token` fallback (which would be mcp.example.com/token).
    assert str(metadata.token_endpoint) == "https://accounts.example.com/oauth/token"
    assert (
        str(metadata.authorization_endpoint)
        == "https://accounts.example.com/oauth/authorize"
    )


def test_known_provider_oauth_metadata_none_for_auto_discovery() -> None:
    assert (
        _known_provider_oauth_metadata(
            _make_mcp_server_stub(provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY)
        )
        is None
    )


def test_known_provider_oauth_metadata_none_without_endpoints() -> None:
    assert (
        _known_provider_oauth_metadata(_make_mcp_server_stub(token_endpoint=None))
        is None
    )


def test_preserves_existing_refresh_token_when_response_omits_it() -> None:
    new_tokens = OAuthToken(
        access_token="new-access", token_type="Bearer", expires_in=3600
    )
    result = _token_dict_with_preserved_refresh(
        new_tokens, {"refresh_token": "old-refresh"}
    )
    assert result["refresh_token"] == "old-refresh"
    assert result["access_token"] == "new-access"


def test_keeps_new_refresh_token_when_present() -> None:
    new_tokens = OAuthToken(
        access_token="a", token_type="Bearer", refresh_token="new-refresh"
    )
    result = _token_dict_with_preserved_refresh(
        new_tokens, {"refresh_token": "old-refresh"}
    )
    assert result["refresh_token"] == "new-refresh"


def test_no_refresh_token_when_none_stored() -> None:
    new_tokens = OAuthToken(access_token="a", token_type="Bearer")
    assert (
        _token_dict_with_preserved_refresh(new_tokens, None).get("refresh_token")
        is None
    )


def test_absolute_token_expiry_from_expires_in() -> None:
    before = time.time()
    expiry = _absolute_token_expiry(
        OAuthToken(access_token="a", token_type="Bearer", expires_in=3600)
    )
    assert expiry is not None
    assert before + 3600 <= expiry <= time.time() + 3600


def test_absolute_token_expiry_none_without_expires_in() -> None:
    assert (
        _absolute_token_expiry(OAuthToken(access_token="a", token_type="Bearer"))
        is None
    )


def _build_provider(provider_mode: MCPOAuthProviderMode) -> OAuthClientProvider:
    return make_oauth_provider(
        _make_mcp_server_stub(provider_mode=provider_mode),
        user_id="user-1",
        return_path="/return",
        connection_config_id=1,
        admin_config_id=None,
    )


def _patch_config_read(
    monkeypatch: pytest.MonkeyPatch, config_data: dict[str, object]
) -> None:
    """Stub out the DB layer so OnyxTokenStorage.get_tokens reads `config_data`."""

    @contextmanager
    def _fake_session() -> Iterator[object]:
        yield object()

    monkeypatch.setattr(mcp_api, "get_session_with_current_tenant", _fake_session)
    monkeypatch.setattr(
        mcp_api.OnyxTokenStorage,
        "_ensure_connection_config",
        lambda _self, _db: object(),
    )
    monkeypatch.setattr(mcp_api, "extract_connection_data", lambda _config: config_data)


def test_make_oauth_provider_sets_known_provider_metadata_and_binds_storage() -> None:
    provider = _build_provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    assert provider.context.oauth_metadata is not None
    # Refresh must target the configured endpoint, not `<server-origin>/token`.
    assert (
        str(provider.context.oauth_metadata.token_endpoint)
        == "https://accounts.example.com/oauth/token"
    )
    # Storage is wired to hydrate expiry from the config read it already does.
    storage = cast(mcp_api.OnyxTokenStorage, provider.context.storage)
    assert storage._oauth_context is provider.context


def test_make_oauth_provider_auto_discovery_leaves_metadata_unset() -> None:
    provider = _build_provider(MCPOAuthProviderMode.AUTO_DISCOVERY)
    assert provider.context.oauth_metadata is None
    assert provider.context.token_expiry_time is None


def test_get_tokens_hydrates_expiry_and_invalidates_expired_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    past = time.time() - 60
    _patch_config_read(
        monkeypatch,
        {
            MCPOAuthKeys.TOKEN_EXPIRES_AT.value: past,
            MCPOAuthKeys.TOKENS.value: {"access_token": "a", "token_type": "Bearer"},
        },
    )
    tokens = asyncio.run(provider.context.storage.get_tokens())
    # Guards the SDK contract: hydrated expiry lands where is_token_valid reads
    # it, so a present-but-expired token is reported invalid (refresh fires).
    assert provider.context.token_expiry_time == past
    provider.context.current_tokens = tokens
    assert provider.context.is_token_valid() is False


def test_get_tokens_clears_stale_expiry_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.AUTO_DISCOVERY)
    provider.context.token_expiry_time = 999.0  # stale value from a prior load
    _patch_config_read(
        monkeypatch,
        {MCPOAuthKeys.TOKENS.value: {"access_token": "a", "token_type": "Bearer"}},
    )
    asyncio.run(provider.context.storage.get_tokens())
    assert provider.context.token_expiry_time is None
