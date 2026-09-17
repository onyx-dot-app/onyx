"""Verify OAuth through Onyx API endpoints and a protected MCP server."""

import ssl
from urllib.parse import parse_qs, urlparse

import httpx

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from tests.integration.common_utils.cimd_oauth import (
    CimdOAuthTestServices,
    MockOidcStatus,
    OAuthHttpsEndpoint,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import (
    DATestLLMProvider,
    DATestPersona,
    DATestUser,
)

MCP_SERVER_NAME = "integration-mcp-cimd"
KNOWN_PROVIDER_SERVER_NAME = "integration-mcp-known-provider"
RETURN_PATH = "/admin/actions/mcp"
MCP_TOOL_NAME = "tool_0"


def _create_oauth_mcp_server(
    services: CimdOAuthTestServices,
    user: DATestUser,
    *,
    name: str,
    provider_mode: MCPOAuthProviderMode,
    authorization_endpoint: str | None = None,
    token_endpoint: str | None = None,
) -> int:
    request: dict[str, object] = {
        "name": name,
        "description": f"{provider_mode.value} OAuth integration server",
        "server_url": services.mcp_server_url,
        "transport": MCPTransport.STREAMABLE_HTTP.value,
        "auth_type": MCPAuthenticationType.OAUTH.value,
        "auth_performer": MCPAuthenticationPerformer.PER_USER.value,
        "oauth_provider_mode": provider_mode.value,
        "is_public": True,
    }
    if provider_mode is MCPOAuthProviderMode.KNOWN_PROVIDER:
        if authorization_endpoint is None or token_endpoint is None:
            raise ValueError("Known-provider test endpoints are required")
        request.update(
            {
                "oauth_client_id": services.client_metadata_url,
                "oauth_authorization_endpoint": authorization_endpoint,
                "oauth_token_endpoint": token_endpoint,
                "oauth_scopes_override": ["mcp:use"],
            }
        )

    response = client.post(
        f"{API_SERVER_URL}/admin/mcp/servers/create",
        json=request,
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return int(response.json()["server_id"])


def _delete_mcp_server(server_id: int, user: DATestUser) -> None:
    response = client.delete(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()


def _available_tool_names(server_id: int, user: DATestUser) -> set[str]:
    response = client.get(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/tools",
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return {tool["name"] for tool in response.json()["tools"]}


def _connect_oauth(
    server_id: int,
    admin_user: DATestUser,
    *,
    force_reauthentication: bool,
) -> dict[str, object]:
    connect_response = client.post(
        f"{API_SERVER_URL}/admin/mcp/oauth/connect",
        json={
            "server_id": server_id,
            "return_path": RETURN_PATH,
            "include_resource_param": True,
            "force_reauthentication": force_reauthentication,
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    connect_response.raise_for_status()
    return connect_response.json()


def _start_oauth_flow(
    server_id: int,
    admin_user: DATestUser,
    services: CimdOAuthTestServices,
    *,
    force_reauthentication: bool,
    authorization_endpoint: str | None = None,
    verify: ssl.SSLContext | bool = True,
) -> dict[str, list[str]]:
    connect_body = _connect_oauth(
        server_id,
        admin_user,
        force_reauthentication=force_reauthentication,
    )
    assert connect_body["status"] == "authorization_required"
    assert connect_body["redirect_url"] == RETURN_PATH
    oauth_url = str(connect_body["authorization_url"])
    expected_endpoint = authorization_endpoint or f"{services.oidc_issuer}/authorize"
    assert oauth_url.startswith(f"{expected_endpoint}?")

    authorization_response = httpx.get(
        oauth_url,
        follow_redirects=False,
        timeout=10,
        verify=verify,
    )
    assert authorization_response.status_code == 302
    callback_url = authorization_response.headers["location"]
    return parse_qs(urlparse(callback_url).query)


def _post_oauth_callback(
    callback_params: dict[str, list[str]],
    user: DATestUser,
) -> httpx.Response:
    return client.post(
        f"{API_SERVER_URL}/mcp/oauth/callback",
        params={
            "code": callback_params["code"][0],
            "state": callback_params["state"][0],
        },
        headers=user.headers,
        cookies=user.cookies,
    )


def _complete_oauth_callback(
    callback_params: dict[str, list[str]],
    user: DATestUser,
) -> None:
    callback_response = _post_oauth_callback(callback_params, user)
    callback_response.raise_for_status()
    assert callback_response.json()["success"] is True


def _complete_oauth_flow(
    server_id: int,
    admin_user: DATestUser,
    services: CimdOAuthTestServices,
    *,
    force_reauthentication: bool,
) -> None:
    callback_params = _start_oauth_flow(
        server_id,
        admin_user,
        services,
        force_reauthentication=force_reauthentication,
    )
    _complete_oauth_callback(callback_params, admin_user)


def test_mcp_oauth_cimd_only_flow(
    cimd_oauth_services: CimdOAuthTestServices,
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    discovery_response = httpx.get(
        f"{cimd_oauth_services.oidc_issuer}/.well-known/oauth-authorization-server",
        timeout=10,
    )
    discovery_response.raise_for_status()
    assert discovery_response.json()["client_id_metadata_document_supported"] is True
    assert "registration_endpoint" not in discovery_response.json()

    server_id = _create_oauth_mcp_server(
        cimd_oauth_services,
        admin_user,
        name=MCP_SERVER_NAME,
        provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
    )
    persona: DATestPersona | None = None

    try:
        first_callback = _start_oauth_flow(
            server_id,
            admin_user,
            cimd_oauth_services,
            force_reauthentication=False,
        )
        second_callback = _start_oauth_flow(
            server_id,
            admin_user,
            cimd_oauth_services,
            force_reauthentication=False,
        )

        wrong_user_response = _post_oauth_callback(first_callback, basic_user)
        assert wrong_user_response.status_code == 400
        assert wrong_user_response.json() == {
            "error_code": "INVALID_INPUT",
            "detail": "Invalid or expired OAuth authorization attempt",
        }

        _complete_oauth_callback(second_callback, admin_user)
        _complete_oauth_callback(first_callback, admin_user)

        replay_response = _post_oauth_callback(second_callback, admin_user)
        assert replay_response.status_code == 400
        assert replay_response.json() == {
            "error_code": "INVALID_INPUT",
            "detail": "Invalid or expired OAuth authorization attempt",
        }

        authenticated_connect = _connect_oauth(
            server_id,
            admin_user,
            force_reauthentication=False,
        )
        assert authenticated_connect["status"] == "already_authenticated"
        assert authenticated_connect["authorization_url"] is None
        assert authenticated_connect["redirect_url"] == RETURN_PATH

        assert MCP_TOOL_NAME in _available_tool_names(server_id, admin_user)

        db_tools_response = client.get(
            f"{API_SERVER_URL}/admin/mcp/server/{server_id}/db-tools",
            headers=admin_user.headers,
            cookies=admin_user.cookies,
        )
        db_tools_response.raise_for_status()
        tool_id = next(
            int(tool["id"])
            for tool in db_tools_response.json()["tools"]
            if tool["name"] == MCP_TOOL_NAME
        )
        persona = PersonaManager.create(
            name="integration-mcp-cimd-persona",
            tool_ids=[tool_id],
            user_performing_action=admin_user,
        )

        _complete_oauth_flow(
            server_id,
            admin_user,
            cimd_oauth_services,
            force_reauthentication=True,
        )

        chat_session = ChatSessionManager.create(
            persona_id=persona.id,
            user_performing_action=admin_user,
        )
        chat_response = ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message="Invoke the CIMD MCP tool.",
            user_performing_action=admin_user,
            forced_tool_ids=[tool_id],
            mock_llm_response=(
                '{"name":"tool_0","arguments":{"name":"integration-test"}}'
            ),
        )
        assert chat_response.error is None
        assert any(
            tool_call.tool_name == MCP_TOOL_NAME
            and tool_call.tool_args == {"name": "integration-test"}
            for tool_call in chat_response.tool_call_debug
        )

        status_response = httpx.get(
            f"{cimd_oauth_services.oidc_issuer}/test/status",
            timeout=10,
        )
        status_response.raise_for_status()
        status = MockOidcStatus.model_validate(status_response.json())
        assert status.client_metadata_fetch_count >= 2
        assert status.registration_request_count == 0
        assert status.last_client_id == cimd_oauth_services.client_metadata_url
    finally:
        if persona is not None:
            assert PersonaManager.delete(persona, admin_user)
        _delete_mcp_server(server_id, admin_user)


def test_mcp_oauth_known_provider_flow(
    cimd_oauth_services: CimdOAuthTestServices,
    known_provider_https_endpoint: OAuthHttpsEndpoint,
    admin_user: DATestUser,
) -> None:
    authorization_endpoint = f"{known_provider_https_endpoint.origin}/authorize"
    token_endpoint = f"{known_provider_https_endpoint.origin}/token"
    server_id = _create_oauth_mcp_server(
        cimd_oauth_services,
        admin_user,
        name=KNOWN_PROVIDER_SERVER_NAME,
        provider_mode=MCPOAuthProviderMode.KNOWN_PROVIDER,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
    )

    try:
        tls_context = ssl.create_default_context(
            cafile=str(known_provider_https_endpoint.ca_file)
        )
        callback = _start_oauth_flow(
            server_id,
            admin_user,
            cimd_oauth_services,
            force_reauthentication=False,
            authorization_endpoint=authorization_endpoint,
            verify=tls_context,
        )
        _complete_oauth_callback(callback, admin_user)

        authenticated_connect = _connect_oauth(
            server_id,
            admin_user,
            force_reauthentication=False,
        )
        assert authenticated_connect == {
            "server_id": server_id,
            "status": "already_authenticated",
            "authorization_url": None,
            "redirect_url": RETURN_PATH,
        }

        reauthentication_callback = _start_oauth_flow(
            server_id,
            admin_user,
            cimd_oauth_services,
            force_reauthentication=True,
            authorization_endpoint=authorization_endpoint,
            verify=tls_context,
        )
        _complete_oauth_callback(reauthentication_callback, admin_user)

        assert MCP_TOOL_NAME in _available_tool_names(server_id, admin_user)
    finally:
        _delete_mcp_server(server_id, admin_user)
