"""Tool binding preserves domain outcomes and failure ownership."""

from unittest.mock import MagicMock

import pytest
import requests

from onyx.agents.models import RunState
from onyx.agents.runtime import Agent
from onyx.agents.tools import ToolInvocation, ToolOutcome
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.interfaces import LLM
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
)
from onyx.tools.interface import ToolContext
from onyx.tools.models import (
    MemoryOperation,
    MemoryUpdated,
    ToolCallException,
    ToolExecutionError,
    ToolExecutionException,
)
from onyx.tools.tool_implementations.memory.memory_tool import MemoryTool
from tests.unit.onyx.agents.fakes import FakeModelClient, run_agent


@pytest.mark.parametrize("failure", ["domain", "defect", "cancel"])
@pytest.mark.parametrize("complete_children", [False, True])
def test_tool_binding_preserves_failure_policy(
    failure: str, complete_children: bool, monkeypatch: pytest.MonkeyPatch
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
    tool.result_from_children = MagicMock(side_effect=error)
    bound = tool.bind(lambda: ToolContext())
    invocation = ToolInvocation(
        call_id="memory",
        arguments={},
        cancellation=CancellationSignal(),
        update=lambda _progress: None,
    )

    def execute() -> ToolOutcome:
        if complete_children:
            assert bound.result_from_children is not None
            return bound.result_from_children(invocation, [])
        return bound.execute(invocation)

    if failure != "cancel":
        result = execute()
        assert isinstance(result, ToolResult)
        assert result.is_error
        assert result.text == (
            "Please provide a memory"
            if failure == "domain"
            else "Tool failed with error: invalid runtime state"
        )
    else:
        with pytest.raises(type(error)) as caught:
            execute()
        assert caught.value is error


@pytest.mark.parametrize(
    "error",
    [
        requests.HTTPError("503 Service Unavailable"),
        ToolExecutionException("Image request rejected by content policy"),
        ValueError("File missing-file does not exist"),
    ],
)
def test_model_can_respond_after_tool_execution_failure(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = MemoryTool(tool_id=1, llm=MagicMock(spec=LLM))
    monkeypatch.setattr(tool, "_run", MagicMock(side_effect=error))
    observed: list[ToolResultMessage] = []

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if request.messages and isinstance(request.messages[-1], ToolResultMessage):
            observed.append(request.messages[-1])
            return AssistantMessage(
                content=[TextContent(text="I can try another way.")]
            )
        return AssistantMessage(
            content=[ToolCall(id="failed-call", name=tool.name, arguments={})]
        )

    result = run_agent(
        Agent(FakeModelClient(generate), tools=[tool.bind(lambda: ToolContext())]),
        max_steps=2,
    )
    assert result.output.text == "I can try another way."
    assert len(observed) == 1
    assert observed[0].tool_call_id == "failed-call"
    assert observed[0].is_error
    assert observed[0].text == f"Tool failed with error: {error}"


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


@pytest.mark.parametrize("display_error", [False, True])
@pytest.mark.parametrize("complete_children", [False, True])
def test_tool_execution_error_keeps_explicit_display_choice(
    display_error: bool, complete_children: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = MemoryTool(tool_id=1, llm=MagicMock(spec=LLM))
    error = ToolExecutionException(
        "Provider rejected request", emit_error_packet=display_error
    )
    monkeypatch.setattr(tool, "_run", MagicMock(side_effect=error))
    tool.result_from_children = MagicMock(side_effect=error)
    bound = tool.bind(lambda: ToolContext())
    invocation = ToolInvocation(
        call_id="failure",
        arguments={},
        cancellation=CancellationSignal(),
        update=lambda _: None,
    )
    if complete_children:
        assert bound.result_from_children is not None
        result = bound.result_from_children(invocation, [])
    else:
        result = bound.execute(invocation)
    assert isinstance(result, ToolResult)
    assert result.is_error
    assert result.content == "Tool failed with error: Provider rejected request"
    if display_error:
        assert isinstance(result.details, ToolExecutionError)
        assert result.details.message == "Provider rejected request"
    else:
        assert result.details is None
