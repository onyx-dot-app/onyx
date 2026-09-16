"""Tool binding preserves domain outcomes and failure ownership."""

from unittest.mock import MagicMock

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import LLM
from onyx.llm.models import ToolResult
from onyx.tools.interface import ToolContext
from onyx.tools.models import ToolCallException
from onyx.tools.progress import MemoryOperation, MemoryUpdated
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from onyx.tools.tool_runner import bind_tool


@pytest.mark.parametrize("failure", ["domain", "defect", "cancel"])
def test_tool_binding_preserves_failure_policy(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = (
        ToolCallException("invalid memory", "Please provide a memory")
        if failure == "domain"
        else RuntimeError("invalid runtime state")
        if failure == "defect"
        else AgentCancelled()
    )
    tool = MemoryTool(tool_id=1, llm=MagicMock(spec=LLM))
    monkeypatch.setattr(tool, "run", MagicMock(side_effect=error))
    execute = bind_tool(tool, ToolContext()).execute
    assert execute is not None
    invocation = ToolInvocation(
        call_id="memory",
        arguments={},
        cancellation=CancellationSignal(),
        update=lambda _progress: None,
    )
    if failure == "domain":
        result = execute(invocation)
        assert result.is_error
        assert result.text == "Please provide a memory"
    else:
        with pytest.raises(type(error)) as caught:
            execute(invocation)
        assert caught.value is error


def test_tool_binding_preserves_complete_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    details = MemoryUpdated(
        memory_text="Prefers tea",
        operation=MemoryOperation.ADD,
        memory_id=42,
        index=None,
    )
    expected = ToolResult(content="Saved", details=details, terminate=True)
    tool = MemoryTool(tool_id=1, llm=MagicMock(spec=LLM))
    monkeypatch.setattr(tool, "run", MagicMock(return_value=expected))
    execute = bind_tool(tool, ToolContext()).execute
    assert execute is not None
    result = execute(
        ToolInvocation(
            call_id="memory",
            arguments={},
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        )
    )
    assert result is expected
    assert result.details is details
    assert result.terminate


def test_tool_binding_checks_cancellation_before_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = MemoryTool(tool_id=1, llm=MagicMock(spec=LLM))
    run = MagicMock()
    monkeypatch.setattr(tool, "run", run)
    execute = bind_tool(tool, ToolContext()).execute
    assert execute is not None
    cancellation = CancellationSignal()
    cancellation.cancel()
    with pytest.raises(AgentCancelled):
        execute(
            ToolInvocation(
                call_id="memory",
                arguments={},
                cancellation=cancellation,
                update=lambda _progress: None,
            )
        )
    run.assert_not_called()
