"""The one sign-in flow: start gives the authorization URL, the callback
stores the connection. Only the remote token endpoint is mocked."""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import requests
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata
from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration import get_external_app_for_integration
from onyx.db.integration_connection import get_connection, get_oauth_client
from onyx.db.models import Integration
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import (
    read_connection_secret,
    read_oauth_client,
)
from onyx.integrations.connections import preset_host_values
from onyx.integrations.oauth import (
    complete_integration_oauth,
    start_integration_oauth,
)
from onyx.server.features.integrations.connections_api import start_oauth
from onyx.server.features.integrations.models import IntegrationOAuthStartRequest
from onyx.server.features.mcp.oauth import OAuthAuthorizationRequired
from onyx.server.features.mcp.oauth_flow import OAuthAuthorizationRedirect
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integrations.conftest import (
    AUTHORIZE_URL,
    TOKEN_URL,
    MakeIntegration,
    token_response,
)


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


@pytest.fixture
def manual_token_post() -> Generator[MagicMock, None, None]:
    post = MagicMock(
        return_value=token_response(
            {
                "access_token": "user-access",
                "refresh_token": "user-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "read write",
            }
        )
    )
    with (
        patch.object(requests, "post", post),
        patch("onyx.auth.oauth_token_manager.validate_oauth_endpoint_url"),
    ):
        yield post


def _manual(
    make_integration: MakeIntegration, mode: IntegrationAuthMode
) -> Integration:
    return make_integration(
        auth_mode=mode,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="manual-client",
        client_secret="manual-secret",
        pkce=True,
        scopes=["read", "write"],
    )


def test_individual_manual_sign_in_stores_user_connection(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    manual_token_post: MagicMock,
) -> None:
    integration = _manual(make_integration, IntegrationAuthMode.INDIVIDUAL)
    user = make_test_user("oauth_individual")

    url = start_integration_oauth(integration, user, db_session, "/plugins")
    query = _query(url)
    assert query["client_id"] == "manual-client"
    assert query["redirect_uri"] == f"{WEB_DOMAIN}/oauth-config/callback"
    assert query["scope"] == "read write"
    assert query["code_challenge_method"] == "S256"

    result = complete_integration_oauth("the-code", query["state"], user, db_session)

    assert result.integration_id == integration.id
    assert result.return_path == "/plugins"
    sent = manual_token_post.call_args.kwargs["data"]
    assert sent["code"] == "the-code"
    assert sent["code_verifier"]
    assert manual_token_post.call_args.args[0] == TOKEN_URL
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    secret = read_connection_secret(connection)
    assert (secret.access_token, secret.refresh_token) == (
        "user-access",
        "user-refresh",
    )
    assert connection.granted_scopes == ["read", "write"]
    assert connection.expires_at is not None
    assert get_connection(db_session, integration.id, None) is None

    # The state is single use.
    with pytest.raises(OnyxError):
        complete_integration_oauth("the-code", query["state"], user, db_session)


def test_shared_sign_in_needs_organization_wide_manage_actions(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    manual_token_post: MagicMock,  # noqa: ARG001
) -> None:
    integration = _manual(make_integration, IntegrationAuthMode.SHARED)
    member = make_test_user("oauth_member")
    admin = make_test_user("oauth_admin", is_admin=True)

    with pytest.raises(OnyxError) as error:
        start_integration_oauth(integration, member, db_session)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    state = _query(start_integration_oauth(integration, admin, db_session))["state"]
    complete_integration_oauth("code", state, admin, db_session)

    assert get_connection(db_session, integration.id, None) is not None
    assert get_connection(db_session, integration.id, admin.id) is None


def test_settings_change_during_sign_in_is_refused(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    manual_token_post: MagicMock,
) -> None:
    integration = _manual(make_integration, IntegrationAuthMode.INDIVIDUAL)
    user = make_test_user("oauth_changed")
    state = _query(start_integration_oauth(integration, user, db_session))["state"]

    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.client_id = "other-client"  # ty: ignore[invalid-assignment]
    db_session.commit()

    with pytest.raises(OnyxError) as error:
        complete_integration_oauth("code", state, user, db_session)
    assert "sign-in settings changed" in error.value.detail
    assert manual_token_post.call_count == 0
    assert get_connection(db_session, integration.id, user.id) is None


def test_preset_sign_in_uses_provider(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.PRESET,
        client_id="linear-client",
        client_secret="linear-secret",
        app_type=ExternalAppType.LINEAR,
    )
    user = make_test_user("oauth_preset")
    url = start_integration_oauth(integration, user, db_session)
    query = _query(url)
    assert urlparse(url).netloc == "linear.app"
    assert query["redirect_uri"] == f"{WEB_DOMAIN}/craft/v1/apps/oauth/callback"

    post = MagicMock(
        return_value=token_response(
            {"access_token": "linear-token", "token_type": "Bearer"}
        )
    )
    with patch.object(requests, "post", post):
        complete_integration_oauth("code", query["state"], user, db_session)
    assert post.call_args.kwargs["data"]["client_secret"] == "linear-secret"
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    assert read_connection_secret(connection).access_token == "linear-token"


def test_preset_host_values_come_from_the_oauth_client(
    db_session: Session, make_integration: MakeIntegration
) -> None:
    preset = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.PRESET,
        client_id="zd-client",
        client_secret="zd-secret",
        app_type=ExternalAppType.ZENDESK,
    )
    manual = _manual(make_integration, IntegrationAuthMode.INDIVIDUAL)
    for integration, params in ((preset, {"subdomain": "acme"}), (manual, {"a": "b"})):
        oauth_client = get_oauth_client(db_session, integration.id)
        assert oauth_client is not None
        oauth_client.additional_params = params
        app = get_external_app_for_integration(integration.id, db_session)
        assert app is not None
        app.organization_credentials = {  # ty: ignore[invalid-assignment]
            "subdomain": "stale"
        }
    db_session.commit()

    assert preset_host_values(preset, db_session) == {"subdomain": "acme"}
    assert preset_host_values(manual, db_session) == {}


def test_mcp_known_provider_sign_in_uses_sdk_exchange(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        kind=IntegrationKind.MCP,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="mcp-client",
    )
    user = make_test_user("oauth_mcp")
    seen: list[httpx.Request] = []

    def token_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "access_token": "mcp-access",
                    "refresh_token": "mcp-refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            ),
            headers={"content-type": "application/json"},
        )

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:  # noqa: ARG001
        return httpx.AsyncClient(transport=httpx.MockTransport(token_handler))

    url = start_integration_oauth(integration, user, db_session)
    query = _query(url)
    assert query["resource"] == "https://mcp.example.test/mcp"
    assert query["client_id"] == "mcp-client"

    with patch(
        "onyx.server.features.mcp.oauth.mcp_ssrf_httpx_client_factory",
        client_factory,
    ):
        complete_integration_oauth("mcp-code", query["state"], user, db_session)

    assert len(seen) == 1
    assert str(seen[0].url) == TOKEN_URL
    sent = parse_qs(seen[0].content.decode())
    assert sent["code"] == ["mcp-code"]
    assert sent["code_verifier"][0]
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    secret = read_connection_secret(connection)
    assert (secret.access_token, secret.refresh_token) == (
        "mcp-access",
        "mcp-refresh",
    )


def test_first_mcp_discovery_sign_in_registers_a_client_and_completes(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    """Dynamic registration writes the client id during the sign-in. The
    callback must still accept the attempt."""
    integration = make_integration(
        kind=IntegrationKind.MCP,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.DISCOVERY,
    )
    user = make_test_user("oauth_mcp_discovery")

    async def discover_and_register(
        oauth_provider: OAuthClientProvider, **_: Any
    ) -> OAuthAuthorizationRedirect:
        context = oauth_provider.context
        context.oauth_metadata = OAuthMetadata(
            issuer=AnyHttpUrl("https://auth.example.test"),
            authorization_endpoint=AnyHttpUrl(AUTHORIZE_URL),
            token_endpoint=AnyHttpUrl(TOKEN_URL),
        )
        registered = OAuthClientInformationFull(
            client_id="registered-client",
            redirect_uris=context.client_metadata.redirect_uris,
            token_endpoint_auth_method="none",
        )
        await context.storage.set_client_info(registered)
        context.client_info = registered
        try:
            await oauth_provider._perform_authorization_code_grant()
        except OAuthAuthorizationRequired as required:
            return OAuthAuthorizationRedirect(
                url=required.authorization.authorization_url
            )
        raise AssertionError("discovery did not stop at the browser boundary")

    seen: list[httpx.Request] = []

    def token_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "access_token": "dcr-access",
                    "refresh_token": "dcr-refresh",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            ),
            headers={"content-type": "application/json"},
        )

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:  # noqa: ARG001
        return httpx.AsyncClient(transport=httpx.MockTransport(token_handler))

    with patch("onyx.integrations.oauth.run_oauth_discovery", discover_and_register):
        url = start_integration_oauth(integration, user, db_session)
    query = _query(url)
    assert query["client_id"] == "registered-client"
    db_session.expire_all()
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    assert read_oauth_client(oauth_client).client_id == "registered-client"

    with patch(
        "onyx.server.features.mcp.oauth.mcp_ssrf_httpx_client_factory",
        client_factory,
    ):
        complete_integration_oauth("dcr-code", query["state"], user, db_session)

    assert len(seen) == 1
    assert str(seen[0].url) == TOKEN_URL
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    assert read_connection_secret(connection).access_token == "dcr-access"


def test_start_route_hides_integrations_the_user_cannot_see(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = _manual(make_integration, IntegrationAuthMode.INDIVIDUAL)
    member = make_test_user("route_member")
    admin = make_test_user("route_admin", is_admin=True)

    with pytest.raises(OnyxError) as error:
        start_oauth(
            integration.id,
            IntegrationOAuthStartRequest(),
            user=member,
            db_session=db_session,
        )
    assert error.value.error_code is OnyxErrorCode.NOT_FOUND

    response = start_oauth(
        integration.id,
        IntegrationOAuthStartRequest(return_path="/plugins"),
        user=admin,
        db_session=db_session,
    )
    assert _query(response.authorization_url)["client_id"] == "manual-client"
