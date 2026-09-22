"""Native compaction and branch persistence regressions."""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from pydantic_ai import messages as pm
from pydantic_ai.models.function import AgentInfo, FunctionModel

from onyx.chat.compression import compact_branch, native_branch_history
from onyx.configs.constants import MessageType
from onyx.db.chat_compaction import (
    find_summary_for_branch,
    get_summary_parent_message_id,
)
from onyx.llm.pydantic_ai_llm import PydanticAILLM

BASE_TIME = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def create_mock_message(
    id: int,
    message: str,
    token_count: int,
    message_type: MessageType = MessageType.USER,
    chat_session_id: int = 1,
    parent_message_id: int | None = None,
    last_summarized_message_id: int | None = None,
    tool_calls: list | None = None,
) -> MagicMock:
    """Create a mock ChatMessage for testing."""
    mock = MagicMock()
    mock.id = id
    mock.message = message
    mock.token_count = token_count
    mock.message_type = message_type
    mock.chat_session_id = chat_session_id
    mock.parent_message_id = parent_message_id
    mock.last_summarized_message_id = last_summarized_message_id
    mock.tool_calls = tool_calls
    # Generate time_sent based on id for chronological ordering
    mock.time_sent = BASE_TIME + timedelta(minutes=id)
    return mock


def test_summary_parent_is_last_user_message() -> None:
    """Summaries parent to the last USER message so every sibling branch
    (multi-model answers, regenerations) can find them."""
    messages = [
        create_mock_message(1, "q1", 100),
        create_mock_message(2, "a1", 100, MessageType.ASSISTANT),
        create_mock_message(3, "q2", 100),
        create_mock_message(4, "a2", 100, MessageType.ASSISTANT),
    ]
    assert (
        get_summary_parent_message_id(messages)  # ty: ignore[invalid-argument-type]
        == 3
    )


def test_summary_parent_falls_back_to_tail_without_user_messages() -> None:
    messages = [
        create_mock_message(1, "a1", 100, MessageType.ASSISTANT),
        create_mock_message(2, "a2", 100, MessageType.ASSISTANT),
    ]
    assert (
        get_summary_parent_message_id(messages)  # ty: ignore[invalid-argument-type]
        == 2
    )


def test_find_summary_for_branch_returns_matching_branch() -> None:
    """Should return summary whose parent_message_id is in current branch."""
    branch_history = [
        create_mock_message(1, "msg1", 100),
        create_mock_message(2, "msg2", 100),
        create_mock_message(3, "msg3", 100),
    ]

    matching_summary = create_mock_message(
        id=100,
        message="Summary of conversation",
        token_count=50,
        parent_message_id=3,
        last_summarized_message_id=2,
    )

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        matching_summary
    ]

    result = find_summary_for_branch(
        mock_db,
        branch_history,  # ty: ignore[invalid-argument-type]
    )

    assert result == matching_summary


def test_find_summary_for_branch_ignores_other_branch() -> None:
    """Should not return summary from a different branch."""
    # Branch B has messages 1, 2, 6, 7 (diverged after message 2)
    branch_b_history = [
        create_mock_message(1, "msg1", 100),
        create_mock_message(2, "msg2", 100),
        create_mock_message(6, "branch b msg1", 100),
        create_mock_message(7, "branch b msg2", 100),
    ]

    # Summary was created on branch A (parent_message_id=5 is NOT in branch B)
    other_branch_summary = create_mock_message(
        id=100,
        message="Summary from branch A",
        token_count=50,
        parent_message_id=5,
        last_summarized_message_id=4,
    )

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
        other_branch_summary
    ]

    result = find_summary_for_branch(
        mock_db,
        branch_b_history,  # ty: ignore[invalid-argument-type]
    )

    assert result is None


@pytest.mark.asyncio
async def test_native_compaction_keeps_latest_exchange_and_updates_previous_summary() -> (
    None
):
    requests: list[list[pm.ModelMessage]] = []

    async def stream(
        messages: list[pm.ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        requests.append(messages)
        assert not info.function_tools
        yield "Preserved important facts."

    llm = MagicMock(spec=PydanticAILLM)
    llm.model = FunctionModel(stream_function=stream)
    llm.model_settings.return_value = {}
    history: list[pm.ModelMessage] = [
        pm.ModelRequest(
            parts=[
                pm.SystemPromptPart(
                    "Summary of previous conversation:\n\nEarlier durable fact."
                )
            ]
        ),
        pm.ModelRequest(parts=[pm.UserPromptPart("Old question " * 200)]),
        pm.ModelResponse(parts=[pm.TextPart("Old answer " * 200)]),
        pm.ModelRequest(parts=[pm.UserPromptPart("Latest question")]),
        pm.ModelResponse(parts=[pm.TextPart("Latest answer")]),
    ]
    compacted = await compact_branch(history, llm=llm, input_budget=1000, tokenizer=len)
    assert compacted[-2:] == history[-2:]
    assert len(requests) == 1
    assert "Earlier durable fact." in str(requests[0])
    assert "previous-summary" in str(requests[0])
    assert "Preserved important facts." in str(compacted[0])
    llm.record_usage.assert_called_once()
    unchanged = await compact_branch(
        compacted, llm=llm, input_budget=1000, tokenizer=len
    )
    assert unchanged == compacted
    assert len(requests) == 1


def test_persisted_native_history_keeps_answers_with_tool_calls() -> None:
    call = MagicMock()
    call.tool_name = None
    call.tool_id = 42
    call.tool_call_id = "search-1"
    call.tool_call_arguments = {"query": "fact"}
    call.tool_call_response = "Tool evidence"
    row = create_mock_message(
        2, "The final answer", 20, MessageType.ASSISTANT, tool_calls=[call]
    )
    native = native_branch_history([row], None, {42: "search"})
    assert all(message.metadata == {"onyx_message_id": 2} for message in native)
    assert "Tool evidence" in str(native)
    assert "The final answer" in str(native)
    assert isinstance(native[0].parts[0], pm.ToolCallPart)
    assert isinstance(native[1].parts[0], pm.ToolReturnPart)


@pytest.mark.asyncio
@pytest.mark.parametrize("over_threshold", [False, True])
async def test_native_tier_uses_configured_trigger_ratio(over_threshold: bool) -> None:
    from onyx.configs.chat_configs import COMPRESSION_TRIGGER_RATIO

    calls = 0

    async def stream(
        messages: list[pm.ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        nonlocal calls
        del messages, info
        calls += 1
        yield "Summary."

    llm = MagicMock(spec=PydanticAILLM)
    llm.model = FunctionModel(stream_function=stream)
    llm.model_settings.return_value = {}
    threshold = int(1000 * COMPRESSION_TRIGGER_RATIO)
    history: list[pm.ModelMessage] = [
        pm.ModelRequest(
            parts=[
                pm.UserPromptPart(
                    "x" * (threshold - 20 + (50 if over_threshold else -50))
                )
            ]
        ),
        pm.ModelResponse(parts=[pm.TextPart("answer")]),
        pm.ModelRequest(parts=[pm.UserPromptPart("latest")]),
        pm.ModelResponse(parts=[pm.TextPart("answer")]),
    ]
    await compact_branch(history, llm=llm, input_budget=1000, tokenizer=len)
    assert calls == int(over_threshold)
