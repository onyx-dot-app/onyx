"""Tool binding preserves domain outcomes and failure ownership."""

from unittest.mock import MagicMock

import pytest

from onyx.agents.models import RunState
from onyx.agents.tools import ToolInvocation
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import LLM
from onyx.llm.models import ToolResult
from onyx.tools.interface import ToolContext
from onyx.tools.models import MemoryOperation, MemoryUpdated, ToolCallException
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool


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
    monkeypatch.setattr(tool, "_run", MagicMock(side_effect=error))
    execute = tool.bind(lambda: ToolContext()).execute
    assert execute is not None
    invocation = ToolInvocation(
        call_id="memory",
        arguments={},
        cancellation=CancellationSignal(),
        update=lambda _progress: None,
    )
    if failure == "domain":
        result = execute(invocation)
        assert isinstance(result, ToolResult)
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
    monkeypatch.setattr(tool, "_run", MagicMock(return_value=expected))
    bound_tool = tool.bind(lambda: ToolContext())
    assert bound_tool.result_from_children is None
    result = bound_tool.execute(
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
    monkeypatch.setattr(tool, "_run", run)
    execute = tool.bind(lambda: ToolContext()).execute
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


def test_binding_resolves_context_when_execution_and_completion_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = MemoryTool(tool_id=1, llm=MagicMock(spec=LLM))
    output = ToolResult(content="Done")
    run = MagicMock(return_value=output)
    monkeypatch.setattr(tool, "_run", run)
    observed_contexts: list[ToolContext] = []

    def complete(
        _invocation: ToolInvocation, context: ToolContext, _children: list[RunState]
    ) -> ToolResult:
        observed_contexts.append(context)
        return output

    tool.result_from_children = complete
    context = ToolContext(next_citation_num=1)
    context_reads = 0

    def get_context() -> ToolContext:
        nonlocal context_reads
        context_reads += 1
        return context

    bound = tool.bind(get_context)
    assert context_reads == 0
    invocation = ToolInvocation(
        call_id="memory",
        arguments={},
        cancellation=CancellationSignal(),
        update=lambda _progress: None,
    )
    context = ToolContext(next_citation_num=5)
    assert bound.execute(invocation) is output
    run.assert_called_once_with(invocation, context)
    context = ToolContext(next_citation_num=10)
    assert bound.result_from_children is not None
    assert bound.result_from_children(invocation, []) is output
    assert observed_contexts == [context]
    assert context_reads == 2
