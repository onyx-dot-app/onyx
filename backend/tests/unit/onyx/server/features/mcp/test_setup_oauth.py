from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import oauth_flow, setup_oauth
from onyx.server.features.mcp.models import MCPSetupRequest
from tests.unit.fakes import FakeCache


def _request() -> MCPSetupRequest:
    return MCPSetupRequest(
        name="Draft",
        server_url="https://mcp.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        oauth_provider_mode=MCPOAuthProviderMode.KNOWN_PROVIDER,
        oauth_client_id="client",
        oauth_client_secret="client-secret",
        oauth_authorization_endpoint="https://auth.example.com/authorize",
        oauth_token_endpoint="https://auth.example.com/token",
    )


@pytest.fixture
def cache(monkeypatch: pytest.MonkeyPatch) -> FakeCache:
    cache = FakeCache()
    monkeypatch.setattr(
        setup_oauth.SETUP_OAUTH_ATTEMPTS, "_cache_backend_provider", lambda: cache
    )
    return cache


@pytest.mark.asyncio
async def test_attempt_is_owner_bound_single_use_and_uses_credential_protection(
    cache: FakeCache,
) -> None:
    encrypted_values: dict[bytes, str] = {}

    def encrypt(value: str) -> bytes:
        encrypted_values[b"encrypted-draft"] = value
        return b"encrypted-draft"

    with (
        patch.object(setup_oauth, "encrypt_string_to_bytes", side_effect=encrypt),
        patch.object(
            setup_oauth,
            "decrypt_bytes_to_string",
            side_effect=encrypted_values.__getitem__,
        ),
    ):
        provider, storage, url = await setup_oauth.start_setup_oauth(
            _request(), "owner", {}, expected_configuration_fingerprint="a" * 64
        )
        assert url is not None
        state = parse_qs(urlparse(url).query)["state"][0]
        assert state.startswith(setup_oauth.SETUP_OAUTH_STATE_PREFIX)
        assert set(cache.expiries.values()) == {600}
        assert b"client-secret" not in next(iter(cache.store.values()))
        assert storage.tokens is None
        assert provider.context.oauth_metadata is not None
        with pytest.raises(OnyxError):
            setup_oauth.consume_setup_oauth(state, "other-owner")
        attempt = setup_oauth.consume_setup_oauth(state, "owner")
        assert attempt.request == _request()
        assert attempt.expected_configuration_fingerprint == "a" * 64
        assert attempt.client_information.client_secret == "client-secret"
        assert attempt.resource == _request().server_url
        assert parse_qs(urlparse(url).query)["resource"] == [_request().server_url]
        assert len(attempt.code_verifier) >= 43
        with pytest.raises(OnyxError):
            setup_oauth.consume_setup_oauth(state, "owner")


@pytest.mark.asyncio
async def test_completed_grant_stays_in_memory_until_caller_publishes(
    cache: FakeCache,
) -> None:
    _, _, url = await setup_oauth.start_setup_oauth(
        _request(), "owner", {"X-Tenant": "test"}
    )
    assert url is not None
    state = parse_qs(urlparse(url).query)["state"][0]
    attempt = setup_oauth.consume_setup_oauth(state, "owner")
    tokens = OAuthToken(
        access_token="access",
        refresh_token="refresh",
        token_type="Bearer",
        expires_in=3600,
    )

    async def exchange(
        self: setup_oauth.OnyxOAuthClientProvider,
        code: str,
        verifier: str,
        *,
        resource: str | None,
    ) -> OAuthToken:
        assert resource == attempt.resource
        assert code == "code"
        assert verifier == attempt.code_verifier
        assert self.context.client_info == attempt.client_information
        assert self.context.oauth_metadata == attempt.oauth_metadata
        await self.context.storage.set_tokens(tokens)
        return tokens

    with patch.object(
        setup_oauth.OnyxOAuthClientProvider,
        "complete_authorization_code_exchange",
        new=exchange,
    ):
        provider, storage = await setup_oauth.complete_setup_oauth(attempt, "code")
    data = storage.connection_data(provider.context)
    assert data["tokens"]["access_token"] == "access"
    assert data["tokens"]["refresh_token"] == "refresh"
    assert data["client_info"]["client_id"] == "client"
    assert data["metadata"]["token_endpoint"] == "https://auth.example.com/token"
    assert data["token_expires_at"] is not None
    assert not cache.store


@pytest.mark.asyncio
async def test_failed_exchange_leaves_no_attempt_or_grant(cache: FakeCache) -> None:
    _, _, url = await setup_oauth.start_setup_oauth(_request(), "owner", {})
    assert url is not None
    state = parse_qs(urlparse(url).query)["state"][0]
    attempt = setup_oauth.consume_setup_oauth(state, "owner")
    with patch.object(
        setup_oauth.OnyxOAuthClientProvider,
        "complete_authorization_code_exchange",
        new=AsyncMock(side_effect=RuntimeError("exchange failed")),
    ):
        with pytest.raises(RuntimeError, match="exchange failed"):
            await setup_oauth.complete_setup_oauth(attempt, "code")
    assert not cache.store


@pytest.mark.asyncio
async def test_transient_storage_preserves_registration_and_expiry() -> None:
    storage = setup_oauth.TransientTokenStorage()
    client = OAuthClientInformationFull(
        client_id="registered", redirect_uris=["https://onyx.example/callback"]
    )
    await storage.set_client_info(client)
    assert await storage.get_client_info() == client
    tokens = OAuthToken(access_token="token", token_type="Bearer", expires_in=120)
    with patch.object(setup_oauth.time, "time", return_value=1000):
        await storage.set_tokens(tokens)
    assert await storage.get_tokens() == tokens
    assert storage.token_expires_at == 1090


@pytest.mark.asyncio
async def test_auto_discovery_saves_prefixed_state_and_restorable_context(
    cache: FakeCache,
) -> None:
    request = _request().model_copy(
        update={
            "oauth_provider_mode": MCPOAuthProviderMode.AUTO_DISCOVERY,
            "transport": setup_oauth.MCPTransport.SSE,
        }
    )

    async def discover(
        *,
        oauth_provider: setup_oauth.OnyxOAuthClientProvider,
        server_url: str,
        connection_headers: dict[str, str],
        transport: setup_oauth.MCPTransport,
    ) -> setup_oauth.OAuthAuthorizationRedirect:
        assert server_url == request.server_url
        assert connection_headers == {"X-Tenant": "tenant"}
        assert transport is setup_oauth.MCPTransport.STREAMABLE_HTTP
        context = oauth_provider.context
        context.client_info = await context.storage.get_client_info()
        context.oauth_metadata = setup_oauth.OAuthMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )
        authorization = oauth_provider.build_resumable_authorization_request()
        assert oauth_provider.authorization_request_handler is not None
        await oauth_provider.authorization_request_handler(authorization, context)
        return setup_oauth.OAuthAuthorizationRedirect(authorization.authorization_url)

    with patch.object(setup_oauth, "run_oauth_discovery", side_effect=discover):
        _, storage, url = await setup_oauth.start_setup_oauth(
            request, "owner", {"X-Tenant": "tenant"}
        )
    assert url is not None
    state = parse_qs(urlparse(url).query)["state"][0]
    assert state.startswith(setup_oauth.SETUP_OAUTH_STATE_PREFIX)
    attempt = setup_oauth.consume_setup_oauth(state, "owner")
    assert attempt.oauth_metadata is not None
    assert (
        str(attempt.oauth_metadata.token_endpoint) == "https://auth.example.com/token"
    )
    assert storage.tokens is None
    assert not cache.store


@pytest.mark.asyncio
async def test_rejected_client_metadata_document_stores_no_attempt(
    cache: FakeCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request().model_copy(
        update={
            "oauth_provider_mode": MCPOAuthProviderMode.AUTO_DISCOVERY,
            "oauth_client_id": "https://onyx.example/api/mcp/oauth/client-metadata",
            "oauth_client_secret": None,
        }
    )

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, request=request)

    monkeypatch.setattr(
        oauth_flow,
        "mcp_ssrf_httpx_client_factory",
        lambda **_kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reject)),
    )

    async def discover(
        *, oauth_provider: setup_oauth.OnyxOAuthClientProvider, **_kwargs: object
    ) -> None:
        context = oauth_provider.context
        context.client_info = await context.storage.get_client_info()
        authorization = oauth_provider.build_resumable_authorization_request()
        assert oauth_provider.authorization_request_handler is not None
        await oauth_provider.authorization_request_handler(authorization, context)

    with patch.object(setup_oauth, "run_oauth_discovery", side_effect=discover):
        with pytest.raises(OnyxError) as exc_info:
            await setup_oauth.start_setup_oauth(request, "owner", {})
    assert exc_info.value.extra == {"oauth_error": "client_metadata_rejected"}
    assert not cache.store


@pytest.mark.asyncio
async def test_existing_registration_keeps_negotiated_token_auth(
    cache: FakeCache,
) -> None:
    registration = OAuthClientInformationFull(
        client_id="client",
        client_secret="client-secret",
        redirect_uris=["https://onyx.example.com/mcp/oauth/callback"],
        token_endpoint_auth_method="client_secret_basic",
        client_id_issued_at=1234567890,
    )
    _, _, url = await setup_oauth.start_setup_oauth(
        _request(), "owner", {}, client_information=registration
    )
    assert url is not None
    state = parse_qs(urlparse(url).query)["state"][0]
    attempt = setup_oauth.consume_setup_oauth(state, "owner")
    assert attempt.client_information == registration
    assert not cache.store
    token_request = None

    async def exchange(
        self: setup_oauth.OnyxOAuthClientProvider,
        code: str,
        verifier: str,
        *,
        resource: str | None,
    ) -> OAuthToken:
        nonlocal token_request
        token_request = await self._exchange_token_authorization_code(
            code, verifier, token_data={"resource": resource} if resource else None
        )
        return OAuthToken(access_token="access", token_type="Bearer")

    with patch.object(
        setup_oauth.OnyxOAuthClientProvider,
        "complete_authorization_code_exchange",
        new=exchange,
    ):
        await setup_oauth.complete_setup_oauth(attempt, "code")
    assert token_request is not None
    assert token_request.headers["Authorization"].startswith("Basic ")
    assert b"client_secret=" not in token_request.content
