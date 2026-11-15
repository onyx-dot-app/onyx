"""Chat must not advertise MCP tools that its credential guard would reject."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
)
from onyx.db.models import MCPServer, User
from onyx.llm.interfaces import LLM
from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.server.features.mcp.models import MCPAuthTemplate, MCPConnectionData
from onyx.tools.models import PersonaToolConfiguration, ToolConfiguration
from onyx.tools.tool_constructor import CustomToolConfig, construct_tools
from onyx.tools.tool_implementations.search.search_tool import PersonaSearchInfo

MODULE = "onyx.tools.tool_constructor"


@pytest.mark.parametrize("persona_id", [0, 5])
@pytest.mark.parametrize(
    "auth_type,data,template,login_token,headers,available",
    [
        pytest.param(
            MCPAuthenticationType.API_TOKEN,
            {},
            None,
            None,
            None,
            False,
            id="missing-api-key",
        ),
        pytest.param(
            MCPAuthenticationType.OAUTH, {}, None, None, None, False, id="missing-oauth"
        ),
        pytest.param(
            MCPAuthenticationType.OAUTH,
            {"client_info": {"client_id": "registered"}},
            None,
            None,
            None,
            False,
            id="oauth-registration-only",
        ),
        pytest.param(
            MCPAuthenticationType.PT_OAUTH,
            {},
            None,
            None,
            None,
            False,
            id="missing-login-token",
        ),
        pytest.param(
            MCPAuthenticationType.NONE,
            {},
            MCPAuthTemplate(headers={"X-Key": "{api_key}"}),
            None,
            None,
            False,
            id="missing-template-value",
        ),
        pytest.param(
            MCPAuthenticationType.API_TOKEN,
            {"headers": {"Authorization": "Bearer key"}},
            None,
            None,
            None,
            True,
            id="connected-api-key",
        ),
        pytest.param(
            MCPAuthenticationType.NONE,
            {},
            None,
            None,
            None,
            True,
            id="no-auth-required",
        ),
        pytest.param(
            MCPAuthenticationType.PT_OAUTH,
            {},
            None,
            "login-token",
            None,
            True,
            id="connected-login-token",
        ),
        pytest.param(
            MCPAuthenticationType.API_TOKEN,
            {},
            None,
            None,
            {"Authorization": "Bearer request-key"},
            True,
            id="request-credentials",
        ),
        pytest.param(
            MCPAuthenticationType.API_TOKEN,
            {},
            None,
            None,
            {"Host": "example.com"},
            False,
            id="denylisted-request-headers",
        ),
        pytest.param(
            MCPAuthenticationType.API_TOKEN,
            {"headers": {"Authorization": "Bearer rejected"}, "reauth_required": True},
            None,
            None,
            {"Authorization": "Bearer request-key"},
            False,
            id="rejected-credentials",
        ),
        pytest.param(
            MCPAuthenticationType.OAUTH,
            {
                "tokens": {"access_token": "expired", "token_type": "Bearer"},
                "token_expires_at": 1,
            },
            None,
            None,
            {"Authorization": "Bearer request-key"},
            False,
            id="unrefreshable-oauth",
        ),
        pytest.param(
            MCPAuthenticationType.OAUTH,
            {
                "tokens": {
                    "access_token": "expired",
                    "token_type": "Bearer",
                    "refresh_token": "refresh",
                },
                "token_expires_at": 1,
            },
            None,
            None,
            None,
            True,
            id="refreshable-oauth",
        ),
    ],
)
def test_chat_mcp_tools_require_usable_credentials(
    persona_id: int,
    auth_type: MCPAuthenticationType,
    data: MCPConnectionData,
    template: MCPAuthTemplate | None,
    login_token: str | None,
    headers: dict[str, str] | None,
    available: bool,
) -> None:
    """Both chat surfaces filter tools and resolve each server only once."""
    credentials = ResolvedMCPCredentials(
        connection_config_id=None,
        connection_data=data,
        user_oauth_token=login_token,
        auth_type=auth_type,
        auth_template=template,
    )
    server = MCPServer(
        id=1,
        name="Example",
        server_url="https://mcp.example.com/mcp",
        auth_type=auth_type,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_cimd_enabled=True,
    )
    configuration = PersonaToolConfiguration(
        persona_id=persona_id,
        persona_name="Test agent",
        tools=[
            ToolConfiguration(
                id=tool_id,
                name=f"action_{tool_id}",
                display_name=f"action_{tool_id}",
                description="Example action",
                in_code_tool_id=None,
                enabled=True,
                openapi_schema=None,
                mcp_input_schema={},
                mcp_output_schema=None,
                custom_headers=None,
                passthrough_auth=False,
                mcp_server_id=server.id,
                oauth_config_id=None,
            )
            for tool_id in (1, 2)
        ],
        search=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
    )
    user = User(id=uuid4(), email="member@example.com", enable_memory_tool=False)
    with (
        patch(f"{MODULE}.get_current_search_settings"),
        patch(f"{MODULE}.get_default_document_index"),
        patch(f"{MODULE}.get_mcp_server_by_id", return_value=server) as get_server,
        patch(f"{MODULE}.resolve_mcp_credentials", return_value=credentials) as resolve,
        patch(f"{MODULE}.get_mcp_server_user_preferences", return_value={}),
        patch(f"{MODULE}.get_tool_user_preferences", return_value={}),
        patch(f"{MODULE}.user_can_access_mcp_server", return_value=True),
    ):
        result = construct_tools(
            configuration=configuration,
            user=user,
            llm=MagicMock(spec=LLM),
            db_session=MagicMock(spec=Session),
            custom_tool_config=CustomToolConfig(mcp_headers=headers),
        )
    assert set(result) == ({1, 2} if available else set())
    assert [
        tool.tool_definition().name for tools in result.values() for tool in tools
    ] == (
        ["mcp__1__Example__action_1", "mcp__1__Example__action_2"] if available else []
    )

    get_server.assert_called_once()
    resolve.assert_called_once()
