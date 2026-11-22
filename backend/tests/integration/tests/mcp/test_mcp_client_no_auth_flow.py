import json

from onyx.db.enums import (
    IntegrationActionPolicyValue,
)
from tests.integration.common_utils.integration_rows import (
    link_persona,
    only_actions,
    set_admin_policies,
)
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)
from tests.integration.tests.mcp.conftest import (
    ConnectedMCPServer,
)

MCP_HELLO_TOOL = "hello"


def test_mcp_json_tool_result_reaches_llm_encoded_once(
    connected_mcp_server: ConnectedMCPServer,
    admin_user: DATestUser,
    mock_llm: MockLLMScript,
) -> None:
    """A tool result that the MCP server sends as JSON text reaches the LLM as
    JSON inside `tool_result`, not as an escaped string."""
    # The tool runs without asking, so the call does not wait for approval.
    set_admin_policies(
        connected_mcp_server.integration_id,
        {"get_ticket": IntegrationActionPolicyValue.ALLOW},
    )

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
    persona = PersonaManager.create(tool_ids=[], user_performing_action=admin_user)
    link_persona(
        persona.id, connected_mcp_server.integration_id, only_actions(["get_ticket"])
    )
    chat_session = ChatSessionManager.create(
        persona_id=persona.id, user_performing_action=admin_user
    )
    ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is ticket 12 about?",
        user_performing_action=admin_user,
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
