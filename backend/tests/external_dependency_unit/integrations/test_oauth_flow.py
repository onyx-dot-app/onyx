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
from fastapi import Request
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthMetadata
from pydantic import AnyHttpUrl
from sqlalchemy.orm import Session

from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationOAuthProviderMode,
    Permission,
)
from onyx.db.integration import (
    get_external_app_for_integration,
    get_mcp_server_for_integration,
)
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
from onyx.server.features.integrations.connections_api import (
    oauth_callback,
    start_oauth,
)
from onyx.server.features.integrations.models import (
    IntegrationOAuthCallbackRequest,
    IntegrationOAuthStartRequest,
)
from onyx.server.features.mcp.oauth import OAuthAuthorizationRequired
from onyx.server.features.mcp.oauth_flow import OAuthAuthorizationRedirect
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    make_app_integration,
    make_mcp_integration,
)
from tests.external_dependency_unit.integrations.conftest import (
    AUTHORIZE_URL,
    TOKEN_URL,
    new_oauth_client,
    token_response,
)


def _http_request(token_scopes: list[Permission] | None) -> Request:
    request = Request({"type": "http"})
    if token_scopes is not None:
        request.state.token_scopes = token_scopes
    return request


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


def _manual(db_session: Session, mode: IntegrationAuthMode) -> Integration:
    return make_app_integration(
        db_session,
        auth_mode=mode,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL,
            client_id="manual-client",
            client_secret="manual-secret",
            pkce=True,
            scopes=["read", "write"],
        ),
    )[0]


def test_individual_manual_sign_in_stores_user_connection(
    db_session: Session,
    make_test_user: MakeTestUser,
    manual_token_post: MagicMock,
) -> None:
    integration = _manual(db_session, IntegrationAuthMode.INDIVIDUAL)
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
    make_test_user: MakeTestUser,
    manual_token_post: MagicMock,  # noqa: ARG001
) -> None:
    integration = _manual(db_session, IntegrationAuthMode.SHARED)
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
    make_test_user: MakeTestUser,
    manual_token_post: MagicMock,
) -> None:
    integration = _manual(db_session, IntegrationAuthMode.INDIVIDUAL)
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


def _change_client_id(integration_id: int) -> None:
    with get_session_with_current_tenant() as other_session:
        oauth_client = get_oauth_client(other_session, integration_id)
        assert oauth_client is not None
        oauth_client.client_id = "other-client"  # ty: ignore[invalid-assignment]
        other_session.commit()


@pytest.mark.parametrize("preset", [False, True], ids=["manual", "preset"])
def test_settings_change_during_the_token_exchange_is_refused(
    db_session: Session,
    make_test_user: MakeTestUser,
    preset: bool,
) -> None:
    integration = (
        make_app_integration(
            db_session,
            auth_mode=IntegrationAuthMode.INDIVIDUAL,
            auth_method=IntegrationAuthMethod.OAUTH2,
            app_type=ExternalAppType.LINEAR,
            oauth_client=new_oauth_client(
                IntegrationOAuthProviderMode.PRESET,
                client_id="linear-client",
                client_secret="linear-secret",
            ),
        )[0]
        if preset
        else _manual(db_session, IntegrationAuthMode.INDIVIDUAL)
    )
    user = make_test_user("oauth_changed_during_exchange")
    state = _query(start_integration_oauth(integration, user, db_session))["state"]

    def post(*_: object, **__: object) -> MagicMock:
        _change_client_id(integration.id)
        return token_response({"access_token": "old-grant", "token_type": "Bearer"})

    with (
        patch.object(requests, "post", post),
        patch("onyx.auth.oauth_token_manager.validate_oauth_endpoint_url"),
        pytest.raises(OnyxError) as error,
    ):
        complete_integration_oauth("code", state, user, db_session)

    assert "sign-in settings changed" in error.value.detail
    db_session.rollback()
    assert get_connection(db_session, integration.id, user.id) is None


def test_preset_sign_in_uses_provider(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        app_type=ExternalAppType.LINEAR,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            client_id="linear-client",
            client_secret="linear-secret",
        ),
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
    db_session: Session,
) -> None:
    preset, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        app_type=ExternalAppType.ZENDESK,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            client_id="zd-client",
            client_secret="zd-secret",
        ),
    )
    manual = _manual(db_session, IntegrationAuthMode.INDIVIDUAL)
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
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL, client_id="mcp-client"
        ),
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


def test_mcp_server_change_during_the_token_exchange_is_refused(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL, client_id="mcp-client"
        ),
    )
    user = make_test_user("oauth_mcp_changed_during_exchange")

    def token_handler(_: httpx.Request) -> httpx.Response:
        with get_session_with_current_tenant() as other_session:
            server = get_mcp_server_for_integration(integration.id, other_session)
            assert server is not None
            server.server_url = "https://other.example.test/mcp"
            other_session.commit()
        return httpx.Response(
            200,
            content=json.dumps({"access_token": "old-grant", "token_type": "Bearer"}),
            headers={"content-type": "application/json"},
        )

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:  # noqa: ARG001
        return httpx.AsyncClient(transport=httpx.MockTransport(token_handler))

    state = _query(start_integration_oauth(integration, user, db_session))["state"]
    with (
        patch(
            "onyx.server.features.mcp.oauth.mcp_ssrf_httpx_client_factory",
            client_factory,
        ),
        pytest.raises(OnyxError) as error,
    ):
        complete_integration_oauth("mcp-code", state, user, db_session)

    assert "sign-in settings changed" in error.value.detail
    db_session.rollback()
    assert get_connection(db_session, integration.id, user.id) is None


def test_first_mcp_discovery_sign_in_registers_a_client_and_completes(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    """Dynamic registration writes the client id during the sign-in. The
    callback must still accept the attempt."""
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
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


def test_mcp_registration_after_a_settings_change_is_rejected(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
    )
    user = make_test_user("oauth_mcp_late_registration")

    async def change_settings_then_register(
        oauth_provider: OAuthClientProvider, **_: Any
    ) -> OAuthAuthorizationRedirect:
        with get_session_with_current_tenant() as other_session:
            server = get_mcp_server_for_integration(integration.id, other_session)
            assert server is not None
            server.server_url = "https://other.example.test/mcp"
            other_session.commit()
        context = oauth_provider.context
        await context.storage.set_client_info(
            OAuthClientInformationFull(
                client_id="late-client",
                redirect_uris=context.client_metadata.redirect_uris,
                token_endpoint_auth_method="none",
            )
        )
        raise AssertionError("the late registration was saved")

    with (
        patch(
            "onyx.integrations.oauth.run_oauth_discovery",
            change_settings_then_register,
        ),
        pytest.raises(OnyxError) as error,
    ):
        start_integration_oauth(integration, user, db_session)

    assert "sign-in settings changed" in error.value.detail
    db_session.expire_all()
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    assert read_oauth_client(oauth_client).client_id is None


def test_mcp_discovery_sends_the_static_headers_of_the_integration(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={
            "Authorization": "Bearer {access_token}",
            "X-Tenant": "acme",
            "X-Key": "{api_key}",
        },
        oauth_client=new_oauth_client(IntegrationOAuthProviderMode.DISCOVERY),
    )
    user = make_test_user("oauth_mcp_headers")
    sent: list[dict[str, str]] = []

    async def discover(
        connection_headers: dict[str, str], **_: Any
    ) -> OAuthAuthorizationRedirect:
        sent.append(connection_headers)
        return OAuthAuthorizationRedirect(url=AUTHORIZE_URL)

    with patch("onyx.integrations.oauth.run_oauth_discovery", discover):
        assert start_integration_oauth(integration, user, db_session) == AUTHORIZE_URL

    assert sent == [{"X-Tenant": "acme"}]


def test_start_route_hides_integrations_the_user_cannot_see(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration = _manual(db_session, IntegrationAuthMode.INDIVIDUAL)
    member = make_test_user("route_member")
    admin = make_test_user("route_admin", is_admin=True)

    with pytest.raises(OnyxError) as error:
        start_oauth(
            _http_request(None),
            integration.id,
            IntegrationOAuthStartRequest(),
            user=member,
            db_session=db_session,
        )
    assert error.value.error_code is OnyxErrorCode.NOT_FOUND

    response = start_oauth(
        _http_request(None),
        integration.id,
        IntegrationOAuthStartRequest(return_path="/plugins"),
        user=admin,
        db_session=db_session,
    )
    assert _query(response.authorization_url)["client_id"] == "manual-client"


def test_shared_sign_in_needs_a_token_that_allows_manage_actions(
    db_session: Session,
    make_test_user: MakeTestUser,
    manual_token_post: MagicMock,  # noqa: ARG001
) -> None:
    shared = _manual(db_session, IntegrationAuthMode.SHARED)
    individual = _manual(db_session, IntegrationAuthMode.INDIVIDUAL)
    admin = make_test_user("token_capped_admin", is_admin=True)
    basic_token = _http_request([Permission.BASIC_ACCESS])

    with pytest.raises(OnyxError) as error:
        start_oauth(
            basic_token,
            shared.id,
            IntegrationOAuthStartRequest(organization=True),
            admin,
            db_session,
        )
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    state = _query(start_integration_oauth(shared, admin, db_session))["state"]
    with pytest.raises(OnyxError) as error:
        oauth_callback(
            basic_token,
            IntegrationOAuthCallbackRequest(code="code", state=state),
            admin,
            db_session,
        )
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert get_connection(db_session, shared.id, None) is None

    # A basic token is enough for an individual sign-in.
    start_oauth(
        basic_token, individual.id, IntegrationOAuthStartRequest(), admin, db_session
    )
