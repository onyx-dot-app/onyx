"""Memory execution commits an outcome before artifacts are serialized."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.chat.artifacts import project_tool_artifacts
from onyx.chat.emitter import Emitter
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage, Message, ToolCall, ToolResultMessage
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.interface import Tool
from onyx.tools.models import MemoryToolResponseSnapshot
from onyx.tools.tool_implementations.memory.memory_tool import (
    MemoryTool,
    MemoryToolOverrideKwargs,
)


@pytest.mark.parametrize(
    "outcome", ["saved", "incognito", "failed", "missing_user", "invalid_index"]
)
def test_memory_outcome_is_final_before_serialization(
    outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    write = MagicMock(return_value=42)
    if outcome == "failed":
        write.side_effect = RuntimeError("storage unavailable")
    elif outcome == "invalid_index":
        write.return_value = None
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.memory.memory_tool.add_memory", write
    )
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.memory.memory_tool.update_memory_at_index",
        write,
    )
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.memory.memory_tool.get_current_incognito_record_mode",
        lambda: "incognito" if outcome == "incognito" else None,
    )
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.memory.memory_tool.process_memory_update",
        lambda **_kwargs: ("Prefers tea", 9 if outcome == "invalid_index" else None),
    )
    result = MemoryTool(1, MagicMock(spec=Emitter), MagicMock(spec=LLM)).run(
        placement=Placement(turn_index=0),
        override_kwargs=MemoryToolOverrideKwargs(
            user_id=None if outcome == "missing_user" else uuid4(),
            user_name=None,
            user_email=None,
            user_role=None,
            existing_memories=[],
            chat_history=[],
        ),
        memory="Prefers tea",
    )
    assert result.is_error is (outcome != "saved")
    if outcome == "saved":
        assert isinstance(result.details, MemoryToolResponseSnapshot)
        assert result.details.memory_id == 42
    else:
        assert result.text.startswith("Error:")
    committed = ToolResultMessage(
        tool_call_id="memory-1",
        tool_name="memory",
        content=result.content,
        details=result.details,
        is_error=result.is_error,
    )
    tool = MagicMock(spec=Tool)
    tool.name = "memory"
    tool.id = 1
    messages: list[Message] = [
        AssistantMessage(
            content=[ToolCall(id="memory-1", name="memory", arguments={})]
        ),
        committed,
    ]
    first = project_tool_artifacts(messages, [tool], lambda _: Placement(turn_index=0))
    second = project_tool_artifacts(messages, [tool], lambda _: Placement(turn_index=0))
    assert first == second
    assert first.tool_calls[0].tool_call_response == result.text
    assert write.call_count == (0 if outcome in {"incognito", "missing_user"} else 1)
