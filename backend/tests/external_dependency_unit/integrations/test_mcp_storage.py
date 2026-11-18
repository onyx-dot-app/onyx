"""The MCP SDK token storage on the integration tables."""

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mcp.client.auth.oauth2 import OAuthContext
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata, OAuthToken
from pydantic import AnyUrl
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import (
    get_connection,
    get_oauth_client,
    mark_connection_needs_reconnect__no_commit,
    set_oauth_client_credentials__no_commit,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import (
    SIGN_IN_REJECTED_REASON,
    SIGN_IN_SETTINGS_CHANGED_REASON,
    read_connection_secret,
    read_oauth_client,
)
from onyx.server.features.mcp import oauth as mcp_oauth
from onyx.server.features.mcp.credentials import (
    mcp_oauth_client_information_fingerprint,
)
from onyx.server.features.mcp.oauth import (
    TOKEN_EXPIRY_BUFFER_SECONDS,
    IntegrationTokenStorage,
    MCPClientRegistrationConflict,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import make_mcp_integration
from tests.external_dependency_unit.integrations.conftest import new_oauth_client


def _client(client_id: str) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl("https://onyx.example.test/mcp/oauth/callback")],
        token_endpoint_auth_method="none",
    )


def test_storage_round_trip(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
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


def test_refreshed_tokens_do_not_revive_a_row_that_needs_reconnect(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
    )
    user = make_test_user("mcp_storage_revive")
    storage = IntegrationTokenStorage(integration.id, user.id)
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a1", refresh_token="r1")))
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    mark_connection_needs_reconnect__no_commit(
        db_session, connection, SIGN_IN_SETTINGS_CHANGED_REASON
    )
    db_session.commit()

    rotated = OAuthToken(access_token="a2", refresh_token="r2")
    assert asyncio.run(storage.set_refreshed_tokens(rotated, "r1")) is False

    db_session.refresh(connection)
    assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert connection.status_reason == SIGN_IN_SETTINGS_CHANGED_REASON
    assert read_connection_secret(connection).access_token == "a1"


def test_entered_client_id_without_registration(
    db_session: Session,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL,
            client_id="own-client",
            client_secret="own-secret",
        ),
    )
    client = asyncio.run(
        IntegrationTokenStorage(integration.id, None).get_client_info()
    )
    assert client is not None
    assert client.client_id == "own-client"
    assert client.client_secret == "own-secret"
    assert client.token_endpoint_auth_method == "client_secret_post"


def test_storage_loads_the_expiry_with_the_refresh_buffer(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
    )
    user = make_test_user("mcp_storage_expiry")
    storage = IntegrationTokenStorage(integration.id, user.id)
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a1", expires_in=3600)))
    context = MagicMock(spec=OAuthContext)
    storage.bind_oauth_context(context)

    asyncio.run(storage.get_tokens())

    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None and connection.expires_at is not None
    assert context.token_expiry_time == (
        connection.expires_at.timestamp() - TOKEN_EXPIRY_BUFFER_SECONDS
    )


def test_grant_for_an_entered_client_that_changed_is_refused(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL,
            client_id="client-a",
            client_secret="secret-a",
        ),
    )
    user = make_test_user("mcp_entered_client_changed")
    started_with = asyncio.run(
        IntegrationTokenStorage(integration.id, user.id).get_client_info()
    )
    assert started_with is not None
    storage = IntegrationTokenStorage(
        integration.id,
        user.id,
        load_stored_tokens=False,
        expected_client_information_fingerprint=(
            mcp_oauth_client_information_fingerprint(started_with)
        ),
    )
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    set_oauth_client_credentials__no_commit(
        db_session,
        oauth_client,
        client_id="client-b",
        client_secret="secret-b",
        registration={},
    )
    db_session.commit()

    with pytest.raises(OnyxError):
        asyncio.run(
            storage.set_authorization_result(
                OAuthToken(access_token="grant-of-a"), started_with
            )
        )
    assert get_connection(db_session, integration.id, user.id) is None

    # An unchanged entered client still saves the grant.
    current = asyncio.run(storage.get_client_info())
    assert current is not None
    unchanged = IntegrationTokenStorage(
        integration.id,
        user.id,
        load_stored_tokens=False,
        expected_client_information_fingerprint=(
            mcp_oauth_client_information_fingerprint(current)
        ),
    )
    asyncio.run(
        unchanged.set_authorization_result(
            OAuthToken(access_token="grant-of-b"), current
        )
    )
    assert get_connection(db_session, integration.id, user.id) is not None


def test_refresh_locks_the_oauth_client_before_the_connection(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    """The sign-in callback locks the OAuth client and then the connection.
    A refresh that saves new metadata must use the same order."""
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
    )
    user = make_test_user("mcp_storage_lock_order")
    storage = IntegrationTokenStorage(integration.id, user.id)
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a1", refresh_token="r1")))
    context = MagicMock(spec=OAuthContext)
    context.oauth_metadata = OAuthMetadata.model_validate(
        {
            "issuer": "https://auth.example.test",
            "authorization_endpoint": "https://auth.example.test/authorize",
            "token_endpoint": "https://auth.example.test/token",
        }
    )
    storage.bind_oauth_context(context)
    locks: list[str] = []
    real_client = mcp_oauth.get_oauth_client
    real_connection = mcp_oauth.get_connection

    def client(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("for_update"):
            locks.append("client")
        return real_client(*args, **kwargs)

    def connection(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("for_update"):
            locks.append("connection")
        return real_connection(*args, **kwargs)

    with (
        patch.object(mcp_oauth, "get_oauth_client", client),
        patch.object(mcp_oauth, "get_connection", connection),
    ):
        assert asyncio.run(
            storage.set_refreshed_tokens(
                OAuthToken(access_token="a2", refresh_token="r2"), "r1"
            )
        )

    assert locks == ["client", "connection"]
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    db_session.refresh(oauth_client)
    assert read_oauth_client(oauth_client).registration["oauth_metadata"]
