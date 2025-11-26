from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage as LangChainSystemMessage

from onyx.agents.agent_framework.message_format import (
    base_messages_to_chat_completion_msgs,
)


def test_base_messages_to_chat_completion_msgs_basic() -> None:
    """Ensure system and user messages convert to chat completion format."""
    system_message = LangChainSystemMessage(
        content="You are a helpful assistant.",
        additional_kwargs={},
        response_metadata={},
    )
    human_message = HumanMessage(
        content="hello",
        additional_kwargs={},
        response_metadata={},
    )

    results = base_messages_to_chat_completion_msgs([system_message, human_message])

    assert results == [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "hello"},
    ]


def test_base_messages_to_chat_completion_msgs_with_tool_call() -> None:
    """Ensure assistant messages with tool calls are preserved."""
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "call_1",
                "name": "internal_search",
                "args": {"query": "test"},
            }
        ],
        additional_kwargs={},
        response_metadata={},
    )

    results = base_messages_to_chat_completion_msgs([ai_message])

    assert len(results) == 1
    assert results[0]["role"] == "assistant"
    assert results[0]["tool_calls"][0]["function"]["name"] == "internal_search"
