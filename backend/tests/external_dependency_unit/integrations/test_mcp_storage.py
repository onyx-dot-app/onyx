"""The MCP SDK token storage on the integration tables."""

import asyncio

import pytest
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import get_connection, get_oauth_client
from onyx.integrations.connection_models import (
    SIGN_IN_REJECTED_REASON,
    read_connection_secret,
)
from onyx.server.features.mcp.oauth import (
    IntegrationTokenStorage,
    MCPClientRegistrationConflict,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integrations.conftest import MakeIntegration


def _client(client_id: str) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl("https://onyx.example.test/mcp/oauth/callback")],
        token_endpoint_auth_method="none",
    )


def test_storage_round_trip(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        kind=IntegrationKind.MCP_SERVER,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.DISCOVERY,
    )
    user = make_test_user("mcp_storage")
    storage = IntegrationTokenStorage(integration.id, user.id)

    assert asyncio.run(storage.get_client_info()) is None
    asyncio.run(storage.set_client_info(_client("dcr-1")))
    assert asyncio.run(storage.get_client_info()) == _client("dcr-1")
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None and oauth_client.client_id is not None
    assert oauth_client.client_id.get_value(apply_mask=False) == "dcr-1"
    # A second registration must not replace the first one.
    with pytest.raises(MCPClientRegistrationConflict):
        asyncio.run(storage.set_client_info(_client("dcr-2")))

    assert asyncio.run(storage.get_tokens()) is None
    asyncio.run(
        storage.set_tokens(
            OAuthToken(
                access_token="a1",
                refresh_token="r1",
                expires_in=3600,
                scope="read write",
            )
        )
    )
    tokens = asyncio.run(storage.get_tokens())
    assert tokens is not None
    assert tokens.access_token == "a1"
    assert tokens.refresh_token == "r1"
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    assert connection.granted_scopes == ["read", "write"]
    assert connection.expires_at is not None

    # Rotation guard: a stale redeemed token does not overwrite the grant.
    rotated = OAuthToken(access_token="a2", refresh_token="r2", expires_in=3600)
    assert asyncio.run(storage.set_refreshed_tokens(rotated, "stale")) is False
    assert asyncio.run(storage.set_refreshed_tokens(rotated, "r1")) is True
    # A refresh response with no refresh token keeps the stored one.
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a3")))
    db_session.refresh(connection)
    secret = read_connection_secret(connection)
    assert (secret.access_token, secret.refresh_token) == ("a3", "r2")

    # A dead grant keeps the row and reads as Needs reconnect.
    assert asyncio.run(storage.discard_persisted_tokens("other")) is False
    assert asyncio.run(storage.discard_persisted_tokens("r2")) is True
    db_session.refresh(connection)
    assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert connection.status_reason == SIGN_IN_REJECTED_REASON
    assert asyncio.run(storage.get_tokens()) is None

    # The organization grant is a separate row.
    organization = IntegrationTokenStorage(integration.id, None)
    asyncio.run(organization.set_tokens(OAuthToken(access_token="org")))
    org_row = get_connection(db_session, integration.id, None)
    assert org_row is not None
    assert read_connection_secret(org_row).access_token == "org"


def test_entered_client_id_without_registration(
    make_integration: MakeIntegration,
) -> None:
    integration = make_integration(
        kind=IntegrationKind.MCP_SERVER,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="own-client",
        client_secret="own-secret",
    )
    client = asyncio.run(
        IntegrationTokenStorage(integration.id, None).get_client_info()
    )
    assert client is not None
    assert client.client_id == "own-client"
    assert client.client_secret == "own-secret"
    assert client.token_endpoint_auth_method == "client_secret_post"
