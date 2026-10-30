"""Model replay omits ambiguous exchanges without changing recorded output."""

import pytest
from pydantic import TypeAdapter

from onyx.agents.execution_records import messages_for_model
from onyx.llm.model_request import format_provider_message
from onyx.llm.models import (
    AssistantMessage,
    Message,
    MessageRole,
    RedactedThinkingBlock,
    TextContent,
    ThinkingBlock,
    ThinkingContent,
    ThinkingDeltaEvent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    apply_generation_event,
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
        AssistantMessage(content=[narration, valid]),
        result,
        later,
        later_result,
    ]
    assert messages == original


@pytest.mark.parametrize("copy_messages", [False, True])
def test_replay_omits_blockless_thinking_without_changing_recorded_output(
    copy_messages: bool,
) -> None:
    partial = AssistantMessage()
    apply_generation_event(
        partial, ThinkingDeltaEvent(content_index=0, text="Partial reasoning")
    )
    answered = AssistantMessage(
        content=[ThinkingContent(text="Reasoning"), TextContent(text="Answer")]
    )
    messages: list[Message] = [partial, UserMessage(content="Continue"), answered]
    original = [message.model_copy(deep=True) for message in messages]

    replay = messages_for_model(messages, copy_messages=copy_messages)

    assert replay == [
        messages[1],
        AssistantMessage(content=[TextContent(text="Answer")]),
    ]
    assert format_provider_message(replay[1]).model_dump(exclude_none=True) == {
        "role": "assistant",
        "content": "Answer",
    }
    assert messages == original


@pytest.mark.parametrize("copy_messages", [False, True])
def test_replay_preserves_signed_blocks_and_omits_unfinished_thinking(
    copy_messages: bool,
) -> None:
    signed = ThinkingBlock(thinking="Completed reasoning", signature="signature")
    redacted = RedactedThinkingBlock(data="opaque")
    partial = ThinkingBlock(thinking="Unfinished reasoning")
    messages: list[Message] = [
        AssistantMessage(
            content=[ThinkingContent(text=partial.thinking, blocks=[partial])],
            stop_reason="aborted",
        ),
        UserMessage(content="Continue"),
        AssistantMessage(
            content=[
                ThinkingContent(
                    text=signed.thinking + partial.thinking,
                    blocks=[signed, redacted, partial],
                ),
                TextContent(text="Partial answer"),
            ],
            stop_reason="error",
        ),
    ]
    original = [message.model_copy(deep=True) for message in messages]

    replay = messages_for_model(messages, copy_messages=copy_messages)

    assert replay == [
        messages[1],
        AssistantMessage(
            content=[
                ThinkingContent(text=signed.thinking, blocks=[signed, redacted]),
                TextContent(text="Partial answer"),
            ],
            stop_reason="error",
        ),
    ]
    wire = format_provider_message(replay[1]).model_dump(exclude_none=True)
    assert wire["thinking_blocks"] == [
        signed.model_dump(),
        redacted.model_dump(),
    ]
    assert messages == original


@pytest.mark.parametrize(
    ("role", "payload"),
    [
        (MessageRole.SYSTEM, '{"role":"system","content":"instructions"}'),
        (MessageRole.USER, '{"role":"user","content":"question"}'),
        (MessageRole.ASSISTANT, '{"role":"assistant","content":[]}'),
        (
            MessageRole.TOOL_RESULT,
            '{"role":"tool_result","tool_call_id":"a","tool_name":"search","content":"result"}',
        ),
    ],
)
def test_message_roles_keep_existing_json(role: MessageRole, payload: str) -> None:
    adapter = TypeAdapter(Message)
    message = adapter.validate_json(payload)
    assert message.role is role
    assert message.role == role.value
    assert message.model_dump(mode="json")["role"] == role.value
    assert adapter.validate_json(adapter.dump_json(message)) == message


def test_replay_preserves_partial_output_and_only_completed_exchanges() -> None:
    assistant = AssistantMessage(
        content=[
            ThinkingContent(text="Inspect the evidence"),
            TextContent(text="Checking sources"),
            ToolCall(id="complete", name="search", arguments={"queries": ["source"]}),
            ToolCall(id="unfinished", name="search", arguments={}),
        ]
    )
    result = ToolResultMessage(
        tool_call_id="complete", tool_name="search", content="Found evidence"
    )
    orphan = ToolResultMessage(
        tool_call_id="unknown", tool_name="search", content="Unrelated result"
    )
    recorded: list[Message] = [assistant, result, orphan]
    before = [message.model_dump_json() for message in recorded]

    replay = messages_for_model(recorded)

    assert len(replay) == 2
    replay_assistant = replay[0]
    assert isinstance(replay_assistant, AssistantMessage)
    assert replay_assistant.text == assistant.text
    assert replay_assistant.thinking == ""
    assert assistant.thinking == "Inspect the evidence"
    assert [call.id for call in replay_assistant.tool_calls] == ["complete"]
    assert replay[1] == result
    replay_assistant.tool_calls[0].arguments["queries"] = ["changed"]
    assert [message.model_dump_json() for message in recorded] == before
    assert replay[1] is not result


def test_replay_does_not_match_results_across_a_user_message() -> None:
    call = AssistantMessage(content=[ToolCall(id="a", name="search", arguments={})])
    user = UserMessage(content="A new request")
    result = ToolResultMessage(tool_call_id="a", tool_name="search", content="late")

    assert messages_for_model([call, user, result]) == [user]
    assert len(call.tool_calls) == 1


def test_replay_can_reuse_owned_content_without_mutating_the_message_list() -> None:
    assistant = AssistantMessage(content=[TextContent(text="Partial answer")])
    user = UserMessage(content="Question")
    recorded: list[Message] = [user, assistant]

    replay = messages_for_model(recorded, copy_messages=False)

    assert replay == recorded
    assert replay is not recorded
    assert replay[0] is user
    assert replay[1] is not assistant
    assert isinstance(replay[1], AssistantMessage)
    assert replay[1].content is not assistant.content
