"""Memory execution commits an outcome before artifacts are serialized."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.agents.models import RunSnapshot
from onyx.agents.tools import ToolInvocation
from onyx.agents.transcript import OperationSnapshot, RunStatus
from onyx.chat.artifacts import project_tool_artifacts
from onyx.db.memory import UserInfo, UserMemoryContext
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import LLM
from onyx.llm.models import AssistantMessage, Message, ToolCall, ToolResultMessage
from onyx.tools.interface import ToolContext
from onyx.tools.models import MemoryUpdated
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool


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
    result = MemoryTool(1, MagicMock(spec=LLM)).run(
        invocation=ToolInvocation(
            call_id="test",
            arguments={"memory": "Prefers tea"},
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        context=ToolContext(
            user_memory_context=UserMemoryContext(
                user_id=None if outcome == "missing_user" else uuid4(),
                user_info=UserInfo(name=None, email=None, role=None),
                memories=tuple([]),
            )
        ),
    )
    assert result.is_error is (outcome != "saved")
    if outcome == "saved":
        assert isinstance(result.details, MemoryUpdated)
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
    messages: list[Message] = [
        AssistantMessage(
            content=[ToolCall(id="memory-1", name="memory", arguments={})]
        ),
        committed,
    ]
    snapshot = RunSnapshot(
        run_id="memory-run",
        status=RunStatus.COMPLETE,
        messages=messages,
        operations=[
            OperationSnapshot(step_index=0, message_index=0, status=RunStatus.COMPLETE),
            OperationSnapshot(
                step_index=0,
                message_index=0,
                tool_call_id="memory-1",
                status=RunStatus.COMPLETE,
            ),
        ],
    )
    projected = project_tool_artifacts(snapshot, {"memory": 1})
    assert projected.tool_calls[0].tool_call_response == result.text
    assert projected.tool_calls[0].result_metadata == result.details
    assert write.call_count == (0 if outcome in {"incognito", "missing_user"} else 1)
