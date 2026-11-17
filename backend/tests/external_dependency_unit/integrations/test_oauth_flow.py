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
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.integration_connection import get_connection, get_oauth_client
from onyx.db.models import ExternalApp, Integration, MCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import read_connection_secret
from onyx.integrations.oauth import (
    complete_integration_oauth,
    start_integration_oauth,
)
from onyx.server.features.integrations.connections_api import (
    IntegrationOAuthStartRequest,
    start_oauth,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integrations.conftest import (
    TOKEN_URL,
    MakeIntegration,
)


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def _token_response(body: dict[str, Any]) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def manual_token_post() -> Generator[MagicMock, None, None]:
    post = MagicMock(
        return_value=_token_response(
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
    )
    app = ExternalApp(
        name=f"Linear {integration.id}",
        app_type=ExternalAppType.LINEAR,
        upstream_url_patterns=[],
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={},
        integration_id=integration.id,
    )
    db_session.add(app)
    db_session.commit()
    user = make_test_user("oauth_preset")
    try:
        url = start_integration_oauth(integration, user, db_session)
        query = _query(url)
        assert urlparse(url).netloc == "linear.app"
        assert query["redirect_uri"] == f"{WEB_DOMAIN}/craft/v1/apps/oauth/callback"

        post = MagicMock(
            return_value=_token_response(
                {"access_token": "linear-token", "token_type": "Bearer"}
            )
        )
        with patch.object(requests, "post", post):
            complete_integration_oauth("code", query["state"], user, db_session)
        assert post.call_args.kwargs["data"]["client_secret"] == "linear-secret"
        connection = get_connection(db_session, integration.id, user.id)
        assert connection is not None
        assert read_connection_secret(connection).access_token == "linear-token"
    finally:
        db_session.rollback()
        db_session.execute(delete(ExternalApp).where(ExternalApp.id == app.id))
        db_session.commit()


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
    server = MCPServer(
        owner=user.email,
        name=f"mcp-{integration.id}",
        server_url="https://mcp.example.test/mcp",
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        integration_id=integration.id,
    )
    db_session.add(server)
    db_session.commit()
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

    try:
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
    finally:
        db_session.rollback()
        db_session.execute(delete(MCPServer).where(MCPServer.id == server.id))
        db_session.commit()


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
