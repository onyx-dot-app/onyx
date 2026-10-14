"""Message details derive displayed thinking from canonical response content."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from onyx.agents.execution_records import ExecutionStatus, RunStatus
from onyx.agents.models import RunState, StepRecord
from onyx.chat.models import MessageRendering, PresentationMode
from onyx.chat.presentation import project_response
from onyx.configs.constants import MessageType
from onyx.db.chat import (
    get_chat_message_reasoning,
    translate_db_message_to_chat_message_detail,
)
from onyx.db.models import ChatMessage, ChatResponseItem
from onyx.llm.models import AssistantMessage, TextContent, ThinkingContent, ToolCall


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RunStatus.COMPLETE, "Accepted thinking"),
        (RunStatus.CANCELLED, "Partial thinking"),
        (RunStatus.LIMIT, "Partial thinking"),
    ],
)
def test_detail_selects_the_same_thinking_as_saved_display(
    status: RunStatus, expected: str
) -> None:
    steps = [
        StepRecord(
            generation_status=ExecutionStatus.COMPLETE,
            message=AssistantMessage(
                id="accepted",
                content=[ThinkingContent(text="Accepted thinking")],
            ),
        ),
        StepRecord(
            generation_status=ExecutionStatus.CANCELLED,
            message=AssistantMessage(
                id="partial",
                content=[ThinkingContent(text="Partial thinking")],
            ),
        ),
        StepRecord(
            generation_status=ExecutionStatus.COMPLETE,
            message=AssistantMessage(
                id="report",
                content=[ThinkingContent(text="Report thinking")],
                metadata=MessageRendering(mode=PresentationMode.REPORT),
            ),
        ),
    ]
    snapshot = RunState(run_id="run", status=status, steps=steps, answer_step_index=0)
    projected = project_response(snapshot, tool_ids={})
    response = ChatMessage(
        id=1,
        chat_session_id=uuid4(),
        message="Answer",
        token_count=1,
        message_type=MessageType.ASSISTANT,
        time_sent=datetime.now(timezone.utc),
        response_status=status,
        response_items=[
            ChatResponseItem(
                id=step.message.id,
                step_index=index,
                message=step.message,
                generation_status=step.generation_status,
                is_answer=index == snapshot.answer_step_index,
                rendering=projected.presentation[step.message.id or ""].model_dump(
                    mode="json"
                ),
            )
            for index, step in reversed(list(enumerate(steps)))
        ],
    )

    assert projected.reasoning == expected
    assert (
        translate_db_message_to_chat_message_detail(response).reasoning_tokens
        == expected
    )


@pytest.mark.parametrize(
    ("text_as_thinking", "think_tool", "expected"),
    [
        (False, None, "Model thinking. "),
        (False, "think", "Model thinking. Tool reasoning. "),
        (True, None, "Model thinking. Text reasoning."),
        (True, "think", "Model thinking. Tool reasoning. Text reasoning."),
    ],
)
def test_detail_preserves_thinking_display_settings(
    text_as_thinking: bool, think_tool: str | None, expected: str
) -> None:
    settings = MessageRendering(
        text_as_thinking=text_as_thinking, think_tool=think_tool
    )
    message = AssistantMessage(
        id="answer",
        metadata=settings,
        content=[
            ThinkingContent(text="Model thinking. "),
            TextContent(text="Text reasoning."),
            ToolCall(
                id="think-1", name="think", arguments={"reasoning": "Tool reasoning. "}
            ),
        ],
    )
    projected = project_response(
        RunState(
            run_id="run",
            status=RunStatus.COMPLETE,
            steps=[
                StepRecord(message=message, generation_status=ExecutionStatus.COMPLETE)
            ],
            answer_step_index=0,
        ),
        tool_ids={},
    )
    response = ChatMessage(
        id=1,
        chat_session_id=uuid4(),
        message="Answer",
        token_count=1,
        message_type=MessageType.ASSISTANT,
        time_sent=datetime.now(timezone.utc),
        response_status=RunStatus.COMPLETE,
        response_items=[
            ChatResponseItem(
                id="answer",
                step_index=0,
                message=message,
                generation_status=ExecutionStatus.COMPLETE,
                is_answer=True,
                rendering=settings.model_dump(mode="json"),
            )
        ],
    )

    assert projected.reasoning == expected
    assert (
        translate_db_message_to_chat_message_detail(response).reasoning_tokens
        == expected
    )


@pytest.mark.parametrize("thinking", ["Legacy thinking", "", None])
def test_legacy_reasoning_preserves_null_and_empty_values(thinking: str | None) -> None:
    response = ChatMessage(response_status=None, reasoning_tokens=thinking)
    assert get_chat_message_reasoning(response) == thinking


@pytest.mark.parametrize("thinking", ["Canonical thinking", "", None])
def test_sdk_reasoning_uses_response_items(thinking: str | None) -> None:
    response = ChatMessage(
        response_status=RunStatus.COMPLETE, reasoning_tokens="Compatibility copy"
    )
    response.response_items.append(
        ChatResponseItem(
            id="answer",
            step_index=0,
            generation_status=ExecutionStatus.COMPLETE,
            message=AssistantMessage(
                content=[ThinkingContent(text=thinking)] if thinking is not None else []
            ),
            is_answer=True,
        )
    )
    assert get_chat_message_reasoning(response) == (thinking or "")
