from unittest.mock import MagicMock, patch

import httpx
import pytest

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
)
from onyx.db.models import MCPServer
from onyx.server.features.mcp.credentials import ResolvedMCPCredentials
from onyx.server.features.mcp.models import MCPAuthTemplate
from onyx.server.metrics.mcp_common import MCPToolCallStatus
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool

MODULE = "onyx.tools.tool_implementations.mcp.mcp_tool"


def _http_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "upstream rejected request",
        request=httpx.Request("POST", "https://mcp.example/mcp"),
        response=httpx.Response(status),
    )


def _wrapped_unauthorized() -> Exception:
    error = RuntimeError("MCP call failed")
    error.__cause__ = ExceptionGroup("transport errors", [_http_error(401)])
    return error


@pytest.mark.parametrize(
    "auth_type,template,replaceable",
    [
        (MCPAuthenticationType.API_TOKEN, None, True),
        (
            MCPAuthenticationType.NONE,
            MCPAuthTemplate(headers={"X-Key": "{api_key}"}),
            True,
        ),
        (
            MCPAuthenticationType.NONE,
            MCPAuthTemplate(headers={"X-Account": "{user_email}"}),
            False,
        ),
        (MCPAuthenticationType.NONE, None, False),
        (
            MCPAuthenticationType.PT_OAUTH,
            MCPAuthTemplate(headers={"X-Key": "{api_key}"}),
            False,
        ),
    ],
)
@pytest.mark.parametrize(
    "error,performer,should_mark",
    [
        (_http_error(401), MCPAuthenticationPerformer.PER_USER, True),
        (_wrapped_unauthorized(), MCPAuthenticationPerformer.PER_USER, True),
        (_http_error(403), MCPAuthenticationPerformer.PER_USER, False),
        (_http_error(503), MCPAuthenticationPerformer.PER_USER, False),
        (httpx.ReadTimeout("timeout"), MCPAuthenticationPerformer.PER_USER, False),
        (ValueError("401 invalid api key"), MCPAuthenticationPerformer.PER_USER, False),
        (_http_error(401), MCPAuthenticationPerformer.ADMIN, False),
    ],
)
def test_only_rejected_user_headers_mark_reauth(
    error: Exception,
    performer: MCPAuthenticationPerformer,
    should_mark: bool,
    auth_type: MCPAuthenticationType,
    template: MCPAuthTemplate | None,
    replaceable: bool,
) -> None:
    credentials = ResolvedMCPCredentials(
        connection_config_id=7,
        connection_data={
            "headers": {"Authorization": "Bearer original"},
            "header_substitutions": {"api_key": "original"},
        },
        user_oauth_token="login-token"
        if auth_type == MCPAuthenticationType.PT_OAUTH
        else None,
        auth_type=auth_type,
        auth_template=template,
    )
    tool = MCPTool(
        tool_id=1,
        emitter=MagicMock(),
        mcp_server=MCPServer(
            id=1,
            name="test",
            server_url="https://mcp.example/mcp",
            auth_type=auth_type,
            auth_performer=performer,
            oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        ),
        tool_name="test",
        tool_description="test",
        tool_definition={},
        resolved_credentials=credentials,
    )
    with (
        patch(f"{MODULE}.call_mcp_tool", side_effect=error),
        patch(f"{MODULE}.get_session_with_current_tenant") as session,
        patch(f"{MODULE}.mark_connection_config_reauth_required") as mark,
        patch(f"{MODULE}.record_mcp_client_tool_outcome") as record_outcome,
    ):
        response = tool.run(Placement(turn_index=0))

    assert "error" in response.llm_facing_response
    unauthorized = (
        isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 401
    )
    wrapped_unauthorized = error.__cause__ is not None
    if unauthorized or wrapped_unauthorized:
        assert "Authentication failed" in response.llm_facing_response
        assert record_outcome.call_args.kwargs["status"] == MCPToolCallStatus.AUTH_ERROR
    if replaceable and (
        should_mark or (auth_type == MCPAuthenticationType.NONE and unauthorized)
    ):
        mark.assert_called_once_with(
            7, credentials.connection_data, session.return_value.__enter__.return_value
        )
    else:
        mark.assert_not_called()
        session.assert_not_called()
