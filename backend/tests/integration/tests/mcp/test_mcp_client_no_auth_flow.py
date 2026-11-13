import json
from uuid import uuid4

from onyx.db.enums import (
    ActionPolicy,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)
from tests.integration.tests.mcp.conftest import (
    NO_AUTH_MCP_SERVER_URL,
    ConnectedMCPServer,
)

MCP_HELLO_TOOL = "hello"


def test_mcp_client_no_auth_flow(
    mcp_no_auth_server: None,  # noqa: ARG001
    admin_user: DATestUser,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,  # noqa: ARG001
) -> None:
    # Step a) Create a no-auth MCP server via the admin API
    create_response = client.post(
        f"{API_SERVER_URL}/admin/mcp/servers/create",
        json={
            "name": f"integration-mcp-no-auth-{uuid4().hex[:8]}",
            "description": "Integration test MCP server",
            "server_url": NO_AUTH_MCP_SERVER_URL,
            "transport": MCPTransport.STREAMABLE_HTTP.value,
            "auth_type": MCPAuthenticationType.NONE.value,
            "auth_performer": MCPAuthenticationPerformer.ADMIN.value,
        },
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    create_response.raise_for_status()
    server_id = create_response.json()["server_id"]

    # Step b) list the server's tools
    tools_response = client.get(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/tools",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    tools_response.raise_for_status()
    tool_entries = tools_response.json()["tools"]
    assert len(tool_entries) == 102

    # Update server status to CONNECTED
    status_response = client.patch(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/status",
        params={"status": "CONNECTED"},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    status_response.raise_for_status()

    tools_response = client.get(
        f"{API_SERVER_URL}/admin/mcp/server/{server_id}/db-tools",
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    tools_response.raise_for_status()
    tool_entries = tools_response.json()["tools"]
    hello_tool_entry = next(
        tool for tool in tool_entries if tool["name"] == MCP_HELLO_TOOL
    )
    tool_id = hello_tool_entry["id"]

    # Step c) Create an assistant (persona) with the MCP tool attached
    persona = PersonaManager.create(
        name=f"integration-mcp-persona-{uuid4().hex[:8]}",
        description="Persona for MCP integration test",
        tool_ids=[tool_id],
        user_performing_action=admin_user,
    )
    persona_tools_response = client.get(
        f"{API_SERVER_URL}/persona",
        headers=basic_user.headers,
        cookies=basic_user.cookies,
    )
    persona_tools_response.raise_for_status()
    persona_entries = persona_tools_response.json()
    persona_entry = next(
        entry for entry in persona_entries if entry["id"] == persona.id
    )
    persona_tool_ids = {tool["id"] for tool in persona_entry["tools"]}
    assert tool_id in persona_tool_ids


def test_mcp_json_tool_result_reaches_llm_encoded_once(
    connected_mcp_server: ConnectedMCPServer,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """A tool result that the MCP server sends as JSON text reaches the LLM as
    JSON inside `tool_result`, not as an escaped string."""
    # The tool runs without asking, so the call does not wait for approval.
    client.patch(
        f"{API_SERVER_URL}/admin/mcp/server/{connected_mcp_server.id}",
        json={"action_policies": {"get_ticket": ActionPolicy.ALWAYS.value}},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    ).raise_for_status()
    tool_id = connected_mcp_server.tool_ids["get_ticket"]

    callable_name = connected_mcp_server.callable_name("get_ticket")
    mock_llm.conversation(
        "chat",
        Reply(
            tool_calls=[
                ToolCall(
                    id="call_ticket", name=callable_name, arguments={"ticket_id": 12}
                )
            ],
            conditions=RequestConditions(offers=[callable_name]),
        ),
        Reply(
            text="Ticket 12 is about the widget parser.",
            conditions=RequestConditions(has_results_for=["call_ticket"]),
        ),
    )
    persona = PersonaManager.create(
        tool_ids=[tool_id], user_performing_action=admin_user
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is ticket 12 about?",
        user_performing_action=admin_user,
        preferred_tool_id=tool_id,
    )

    tool_result = mock_llm.requests_in("chat")[-1].tool_result("call_ticket")
    assert tool_result is not None
    assert json.loads(tool_result) == {
        "tool_result": {
            "id": 12,
            "title": 'Fix the "widget" parser',
            "labels": ["bug"],
        }
    }
