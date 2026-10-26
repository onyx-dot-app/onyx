"""Model replay omits ambiguous exchanges without changing recorded output."""

import pytest

from onyx.agents.execution_records import messages_for_model
from onyx.llm.models import (
    AssistantMessage,
    Message,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
)


@pytest.mark.parametrize("copy_messages", [False, True])
def test_replay_omits_duplicate_call_ids_with_their_results(
    copy_messages: bool,
) -> None:
    narration = TextContent(text="Checking the sources")
    thinking = ThinkingContent(text="Compare the evidence")
    valid = ToolCall(id="valid", name="lookup", arguments={"query": "unique"})
    result = ToolResultMessage(
        tool_call_id="valid", tool_name="lookup", content="Useful evidence"
    )
    later = AssistantMessage(
        content=[ToolCall(id="duplicate", name="lookup", arguments={"query": "later"})]
    )
    later_result = ToolResultMessage(
        tool_call_id="duplicate", tool_name="lookup", content="Later evidence"
    )
    messages: list[Message] = [
        AssistantMessage(
            content=[
                narration,
                ToolCall(id="duplicate", name="lookup", arguments={"query": "first"}),
                thinking,
                valid,
                ToolCall(id="duplicate", name="lookup", arguments={"query": "second"}),
            ]
        ),
        ToolResultMessage(
            tool_call_id="duplicate", tool_name="lookup", content="Ambiguous evidence"
        ),
        result,
        ToolResultMessage(
            tool_call_id="valid", tool_name="lookup", content="Repeated result"
        ),
        later,
        later_result,
    ]
    original = [message.model_copy(deep=True) for message in messages]

    replay = messages_for_model(messages, copy_messages=copy_messages)

    assert replay == [
        AssistantMessage(content=[narration, thinking, valid]),
        result,
        later,
        later_result,
    ]
    assert messages == original
