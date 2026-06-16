import asyncio
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import cast
from typing import Iterator
from urllib.parse import parse_qs
from urllib.parse import urlparse

import httpx
import pytest
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthMetadata
from mcp.shared.auth import OAuthToken
from pydantic import AnyHttpUrl
from pydantic import AnyUrl

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
    # Placeholder host can't resolve; the SSRF guard is exercised in test_mcp_ssrf.
    monkeypatch.setattr(
        "onyx.auth.oauth_token_manager.validate_oauth_endpoint_url",
        lambda url: None,  # noqa: ARG005
    )

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
    # Refresh must hit the configured endpoint, not the SDK's
    # `<server-origin>/token` fallback (mcp.example.com/token).
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
    # The expiry is `now + expires_in` pulled back by the refresh buffer so we
    # refresh slightly early; bound the assertion the same way.
    buffer = mcp_api.TOKEN_EXPIRY_BUFFER_SECONDS
    assert before + 3600 - buffer <= expiry <= time.time() + 3600 - buffer


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
        lambda _self, _db: SimpleNamespace(id=1),
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


# --- Discovered OAuth metadata persistence (AUTO_DISCOVERY cross-host refresh) ---


_DISCOVERED_METADATA = OAuthMetadata(
    issuer=cast(AnyHttpUrl, "https://idp.other-host.com"),
    authorization_endpoint=cast(AnyHttpUrl, "https://idp.other-host.com/authorize"),
    token_endpoint=cast(AnyHttpUrl, "https://idp.other-host.com/token"),
)


def _patch_config_store(
    monkeypatch: pytest.MonkeyPatch, config_data: dict[str, object]
) -> None:
    """Like `_patch_config_read`, but also stubs the write path so `set_tokens`
    persists into the same in-memory `config_data` dict (`extract_connection_data`
    returns it, so mutations land in place; the update is a no-op)."""
    _patch_config_read(monkeypatch, config_data)
    monkeypatch.setattr(
        mcp_api, "update_connection_config", lambda *_args, **_kwargs: None
    )


def test_get_tokens_rehydrates_discovered_metadata_for_auto_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.AUTO_DISCOVERY)
    assert provider.context.oauth_metadata is None
    _patch_config_read(
        monkeypatch,
        {
            MCPOAuthKeys.METADATA.value: _DISCOVERED_METADATA.model_dump(mode="json"),
            MCPOAuthKeys.TOKENS.value: {"access_token": "a", "token_type": "Bearer"},
        },
    )
    asyncio.run(provider.context.storage.get_tokens())
    # Cross-host AUTO_DISCOVERY now refreshes against the discovered endpoint
    # instead of the SDK's `<server-origin>/token` fallback.
    assert provider.context.oauth_metadata is not None
    assert (
        str(provider.context.oauth_metadata.token_endpoint)
        == "https://idp.other-host.com/token"
    )


def test_get_tokens_does_not_override_known_provider_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    # A stale/different persisted metadata must not displace the configured
    # known-provider endpoints that make_oauth_provider injected.
    _patch_config_read(
        monkeypatch,
        {
            MCPOAuthKeys.METADATA.value: _DISCOVERED_METADATA.model_dump(mode="json"),
            MCPOAuthKeys.TOKENS.value: {"access_token": "a", "token_type": "Bearer"},
        },
    )
    asyncio.run(provider.context.storage.get_tokens())
    assert provider.context.oauth_metadata is not None
    assert (
        str(provider.context.oauth_metadata.token_endpoint)
        == "https://accounts.example.com/oauth/token"
    )


def test_set_tokens_persists_discovered_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.AUTO_DISCOVERY)
    # Simulate the SDK having discovered the auth server during the 401 flow.
    provider.context.oauth_metadata = _DISCOVERED_METADATA
    config_data: dict[str, object] = {}
    _patch_config_store(monkeypatch, config_data)
    asyncio.run(
        provider.context.storage.set_tokens(
            OAuthToken(access_token="a", token_type="Bearer", expires_in=3600)
        )
    )
    persisted = cast(dict, config_data.get(MCPOAuthKeys.METADATA.value))
    assert isinstance(persisted, dict)
    assert persisted["token_endpoint"] == "https://idp.other-host.com/token"


# --- End-to-end proactive refresh through the SDK's async_auth_flow ---


def _seed_refreshable_config(expires_at: float) -> dict[str, object]:
    """Stored state for a user whose access token is expired but refreshable."""
    client_info = OAuthClientInformationFull(
        client_id="client-123",
        client_secret="secret-123",
        redirect_uris=[cast(AnyUrl, "https://app.example.com/mcp/oauth/callback")],
    )
    return {
        MCPOAuthKeys.CLIENT_INFO.value: client_info.model_dump(mode="json"),
        MCPOAuthKeys.TOKEN_EXPIRES_AT.value: expires_at,
        MCPOAuthKeys.TOKENS.value: {
            "access_token": "access-old",
            "token_type": "Bearer",
            "refresh_token": "refresh-old",
        },
    }


async def _drive_refresh(
    provider: OAuthClientProvider,
    refresh_status: int,
    refresh_body: dict[str, object],
) -> tuple[httpx.Request, httpx.Request | None]:
    """Drive `async_auth_flow` through its proactive-refresh branch: take the
    first yielded request (the refresh), feed it the given response, and return
    that refresh request plus the next request the SDK would send."""
    request = httpx.Request("POST", "https://mcp.example.com/mcp")
    flow = provider.async_auth_flow(request)
    refresh_request = await anext(flow)
    refresh_response = httpx.Response(
        status_code=refresh_status, json=refresh_body, request=refresh_request
    )
    try:
        next_request: httpx.Request | None = await flow.asend(refresh_response)
    except StopAsyncIteration:
        next_request = None
    await flow.aclose()
    return refresh_request, next_request


def test_proactive_refresh_targets_configured_endpoint_and_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    config_data = _seed_refreshable_config(expires_at=time.time() - 60)
    _patch_config_store(monkeypatch, config_data)

    refresh_request, authed_request = asyncio.run(
        _drive_refresh(
            provider,
            refresh_status=200,
            refresh_body={
                "access_token": "access-new",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "refresh-new",
            },
        )
    )

    # Refresh must hit the configured token endpoint, not <server-origin>/token.
    assert str(refresh_request.url) == "https://accounts.example.com/oauth/token"
    assert b"grant_type=refresh_token" in refresh_request.content
    assert b"refresh-old" in refresh_request.content
    # The in-flight request is retried with the freshly minted token.
    assert authed_request is not None
    assert authed_request.headers.get("Authorization") == "Bearer access-new"
    # The new token + a future expiry are persisted for the next call.
    persisted_tokens = cast(dict, config_data[MCPOAuthKeys.TOKENS.value])
    assert persisted_tokens["access_token"] == "access-new"
    assert persisted_tokens["refresh_token"] == "refresh-new"
    assert cast(float, config_data[MCPOAuthKeys.TOKEN_EXPIRES_AT.value]) > time.time()


def test_proactive_refresh_preserves_refresh_token_when_response_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    config_data = _seed_refreshable_config(expires_at=time.time() - 60)
    _patch_config_store(monkeypatch, config_data)

    _, authed_request = asyncio.run(
        _drive_refresh(
            provider,
            refresh_status=200,
            refresh_body={
                "access_token": "access-new",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    assert authed_request is not None
    persisted_tokens = cast(dict, config_data[MCPOAuthKeys.TOKENS.value])
    assert persisted_tokens["access_token"] == "access-new"
    # Providers that only issue a refresh token once keep working.
    assert persisted_tokens["refresh_token"] == "refresh-old"


def test_proactive_refresh_failure_clears_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _build_provider(MCPOAuthProviderMode.KNOWN_PROVIDER)
    config_data = _seed_refreshable_config(expires_at=time.time() - 60)
    _patch_config_store(monkeypatch, config_data)

    refresh_request, authed_request = asyncio.run(
        _drive_refresh(
            provider,
            refresh_status=400,
            refresh_body={"error": "invalid_grant"},
        )
    )

    # A rejected refresh clears the in-memory token so the SDK falls through to
    # re-auth (which surfaces as "please reconnect" at the tool layer) rather
    # than retrying a dead access token.
    assert str(refresh_request.url) == "https://accounts.example.com/oauth/token"
    assert provider.context.current_tokens is None
    assert authed_request is not None, (
        "SDK no longer yields original request on refresh failure"
    )
    assert authed_request.headers.get("Authorization") is None
