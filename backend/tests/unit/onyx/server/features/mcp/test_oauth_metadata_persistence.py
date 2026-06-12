from typing import Any
from typing import cast

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull
from mcp.shared.auth import OAuthClientMetadata
from mcp.shared.auth import OAuthMetadata
from mcp.shared.auth import OAuthToken
from mcp.shared.auth import ProtectedResourceMetadata
from pydantic import AnyHttpUrl
from pydantic import AnyUrl

from onyx.server.features.mcp.api import MCP_OAUTH_AUTH_SERVER_METADATA_KEY
from onyx.server.features.mcp.api import MCP_OAUTH_AUTH_SERVER_URL_KEY
from onyx.server.features.mcp.api import MCP_OAUTH_PROTECTED_RESOURCE_METADATA_KEY
from onyx.server.features.mcp.api import OnyxOAuthClientProvider
from onyx.server.features.mcp.api import OnyxTokenStorage


class InMemoryOnyxTokenStorage(OnyxTokenStorage):
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info: OAuthClientInformationFull | None = None
        self.metadata: dict[str, object] | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, info: OAuthClientInformationFull) -> None:
        self.client_info = info

    async def get_metadata(self) -> dict[str, object] | None:
        return self.metadata

    async def set_metadata(self, metadata: dict[str, object]) -> None:
        self.metadata = metadata


def _make_client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uris=[AnyUrl("https://onyx.example.com/mcp/oauth/callback")],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="client_secret_post",
    )


def _make_provider(storage: InMemoryOnyxTokenStorage) -> OnyxOAuthClientProvider:
    return OnyxOAuthClientProvider(
        server_url="https://api.githubcopilot.com/mcp",
        client_metadata=OAuthClientMetadata(
            client_name="Onyx - delegated auth test",
            redirect_uris=[AnyUrl("https://onyx.example.com/mcp/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=storage,
    )


def _make_protected_resource_metadata() -> ProtectedResourceMetadata:
    return ProtectedResourceMetadata(
        resource=AnyHttpUrl("https://api.githubcopilot.com/mcp"),
        authorization_servers=[AnyHttpUrl("https://github.com/login/oauth")],
    )


def _make_oauth_metadata() -> OAuthMetadata:
    return OAuthMetadata(
        issuer=AnyHttpUrl("https://github.com/login/oauth"),
        authorization_endpoint=AnyHttpUrl(
            "https://github.com/login/oauth/authorize"
        ),
        token_endpoint=AnyHttpUrl("https://github.com/login/oauth/access_token"),
    )


@pytest.mark.asyncio
async def test_token_response_persists_discovered_oauth_metadata() -> None:
    storage = InMemoryOnyxTokenStorage()
    provider = _make_provider(storage)
    provider.context.protected_resource_metadata = _make_protected_resource_metadata()
    provider.context.oauth_metadata = _make_oauth_metadata()
    provider.context.auth_server_url = "https://github.com/login/oauth"

    await provider._handle_token_response(
        httpx.Response(
            200,
            json={
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        )
    )

    assert storage.metadata is not None
    oauth_metadata = cast(
        dict[str, Any], storage.metadata[MCP_OAUTH_AUTH_SERVER_METADATA_KEY]
    )
    assert (
        oauth_metadata["token_endpoint"]
        == "https://github.com/login/oauth/access_token"
    )
    assert MCP_OAUTH_PROTECTED_RESOURCE_METADATA_KEY in storage.metadata
    assert (
        storage.metadata[MCP_OAUTH_AUTH_SERVER_URL_KEY]
        == "https://github.com/login/oauth"
    )


@pytest.mark.asyncio
async def test_refresh_uses_persisted_oauth_metadata_token_endpoint() -> None:
    storage = InMemoryOnyxTokenStorage()
    storage.client_info = _make_client_info()
    storage.tokens = OAuthToken(
        access_token="expired-access-token",
        refresh_token="refresh-token",
        token_type="Bearer",
        expires_in=1,
    )
    storage.metadata = {
        MCP_OAUTH_PROTECTED_RESOURCE_METADATA_KEY: _make_protected_resource_metadata().model_dump(
            mode="json"
        ),
        MCP_OAUTH_AUTH_SERVER_METADATA_KEY: _make_oauth_metadata().model_dump(
            mode="json"
        ),
        MCP_OAUTH_AUTH_SERVER_URL_KEY: "https://github.com/login/oauth",
    }
    provider = _make_provider(storage)

    await provider._initialize()
    request = await provider._refresh_token()

    assert (
        str(request.url)
        == "https://github.com/login/oauth/access_token"
    )
    assert request.content is not None
    assert b"refresh_token=refresh-token" in request.content
