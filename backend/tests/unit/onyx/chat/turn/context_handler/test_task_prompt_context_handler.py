from collections.abc import Sequence

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import AssistantMessageWithContent
from onyx.agents.agent_sdk.message_types import AssistantMessageWithToolCalls
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import OutputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import ToolCall
from onyx.agents.agent_sdk.message_types import ToolCallFunction
from onyx.agents.agent_sdk.message_types import ToolMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler.task_prompt import update_task_prompt


def test_task_prompt_handler_with_no_user_messages() -> None:
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )
    current_user_message: UserMessage = UserMessage(
        role="user",
        content=[InputTextContent(type="input_text", text="Current query")],
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Assistant message 1")],
        ),
        AssistantMessageWithContent(
            role="assistant",
            content=[OutputTextContent(type="output_text", text="Assistant message 2")],
        ),
    ]

    result = update_task_prompt(
        current_user_message,
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    assert len(result) == 3
    assert result[0].get("role") == "assistant"
    assert result[1].get("role") == "assistant"
    assert result[2].get("role") == "user"


def test_task_prompt_handler_basic() -> None:
    task_prompt = "reminder!"
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt=task_prompt,
        datetime_aware=False,
    )
    current_user_message: UserMessage = UserMessage(
        role="user",
        content=[InputTextContent(type="input_text", text="Query")],
    )
    agent_turn_messages: Sequence[AgentSDKMessage] = [
        SystemMessage(
            role="system",
            content=[InputTextContent(type="input_text", text="hi")],
        ),
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"queries": ["hi"]}',
                        name="internal_search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool message 1",
            tool_call_id="call_1",
        ),
        UserMessage(
            role="user",
            content=[InputTextContent(type="input_text", text="reminder!")],
        ),
        AssistantMessageWithToolCalls(
            role="assistant",
            tool_calls=[
                ToolCall(
                    function=ToolCallFunction(
                        arguments='{"queries": ["hi"]}',
                        name="internal_search",
                    ),
                    id="call_1",
                    type="function",
                )
            ],
        ),
        ToolMessage(
            role="tool",
            content="Tool message 1",
            tool_call_id="call_1",
        ),
    ]

    result = update_task_prompt(
        current_user_message,
        agent_turn_messages,
        prompt_config,
        should_cite_documents=False,
    )

    assert len(result) == 6
    assert result[0].get("role") == "system"
    assert result[1].get("role") == "assistant"
    assert result[2].get("role") == "tool"
    assert result[3].get("role") == "assistant"
    assert result[4].get("role") == "tool"
    assert result[5].get("role") == "user"
    # Type narrow to UserMessage after checking role
    last_msg = result[5]
    if last_msg.get("role") == "user":
        user_msg: UserMessage = last_msg  # type: ignore[assignment]
        # Content is now a list of InputTextContent items
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) > 0
        first_content = user_msg["content"][0]
        if first_content["type"] == "input_text":
            text_content: InputTextContent = first_content  # type: ignore[assignment]
            assert task_prompt in text_content["text"]
