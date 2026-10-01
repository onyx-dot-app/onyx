from onyx.configs.constants import DocumentSource
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.mock_llm import MockLLMScript
from tests.integration.common_utils.test_models import DATestUser, ToolName
from tests.integration.mock_services.mock_llm_server.models import (
    Reply,
    RequestConditions,
    ToolCall,
)

SEARCH_CALL_ID = "call_search_1"
ANSWER = "The PTO policy grants twenty days a year."


def test_scripted_turn_runs_native_internal_search_then_answers(
    admin_user: DATestUser, mock_llm: MockLLMScript
) -> None:
    """A two-reply turn through the mock LLM server: the model calls
    internal_search natively, gets the tool result, and answers."""
    # internal_search is only offered when a non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )
    mock_llm.conversation(
        "chat",
        Reply(
            reasoning="I should search the company docs.",
            tool_calls=[
                ToolCall(
                    id=SEARCH_CALL_ID,
                    name="internal_search",
                    arguments={"queries": ["pto policy"]},
                )
            ],
            conditions=RequestConditions(offers=["internal_search"]),
        ),
        Reply(
            text=ANSWER, conditions=RequestConditions(has_results_for=[SEARCH_CALL_ID])
        ),
    )
    chat_session = ChatSessionManager.create(user_performing_action=admin_user)

    response = ChatSessionManager.send_message(
        chat_session_id=chat_session.id,
        message="What is our PTO policy?",
        user_performing_action=admin_user,
    )

    # The tool ran, and the scripted answer is the final message.
    assert response.error is None, f"Unexpected stream error: {response.error}"
    assert [(d.tool_name, d.tool_args) for d in response.tool_call_debug] == [
        ("internal_search", {"queries": ["pto policy"]})
    ]
    assert [tool.tool_name for tool in response.used_tools] == [
        ToolName.INTERNAL_SEARCH
    ]
    assert response.full_message == ANSWER
    assert response.packets, "expected placed packets in the stream"

    # The second request carries the call and its result back to the model.
    first, second = mock_llm.requests_in("chat")
    assert first.reply_index == 0 and second.reply_index == 1
    assert "internal_search" in first.tools
    assert second.tool_result(SEARCH_CALL_ID) is not None
    assistant_calls = [
        call.id
        for message in second.messages
        if message.role == "assistant"
        for call in message.tool_calls
    ]
    assert assistant_calls == [SEARCH_CALL_ID]

    # The search's own secondary calls got the default reply.
    assert any(r.used_default_reply for r in mock_llm.requests)
