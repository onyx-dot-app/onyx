"""Code mode programs in the agent runtime: the store, compaction and restore."""

import threading

import pytest

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent, ToolEndEvent
from onyx.agents.models import (
    AgentState,
    CompactionCheckpoint,
    ExecutionStatus,
    RunFailureKind,
    RunState,
    RunStatus,
    ToolCallContext,
)
from onyx.agents.runtime import Agent, RunFailed
from onyx.agents.tools import (
    AgentTool,
    ChildRunWait,
    HumanToolAnswer,
    InputDecision,
    InputMode,
    PendingToolInput,
    ToolInvocation,
    ToolOutcome,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    Message,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.code_mode.cells import (
    CodeCells,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    RESTORED_RUNNING_MESSAGE,
    CodeModeTool,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeExecutionResult,
    SandboxLimits,
    StoreCommit,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import EchoTool, FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import LIMITS, FakeTool

WRITE = ToolCall(
    id="write", name=CodeModeTool.NAME, arguments={"code": "store('n', 1)"}
)
READ = ToolCall(
    id="read",
    name=CodeModeTool.NAME,
    arguments={"code": "await echo(value='x')\nprint(load('n') + 1)"},
)


def _answer_with_last_result(
    request: GenerationRequest, _signal: CancellationSignal
) -> AssistantMessage:
    results = [
        message
        for message in request.messages
        if isinstance(message, ToolResultMessage)
    ]
    if results:
        return AssistantMessage(content=[TextContent(text=results[-1].text)])
    return AssistantMessage(content=[WRITE, READ])


def _approve_read(context: ToolCallContext) -> PendingToolInput | None:
    if context.call.id != READ.id:
        return None
    return PendingToolInput(
        request_id="run-read", prompt="Run?", mode=InputMode.EXECUTE
    )


def _agent(
    echo_calls: list[str], *, gate: bool, state: AgentState | None = None
) -> Agent:
    """A fresh agent with a fresh code mode tool, as a new process builds it."""

    def echo(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        echo_calls.append(invocation.call_id)
        return ToolResult(content="echoed")

    tool = CodeModeTool([FakeTool("echo", echo)], cells=CodeCells(), limits=LIMITS)
    return Agent(
        FakeModelClient(_answer_with_last_result),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id="agent",
        state=state,
        tools=[tool.bind(ToolContext)],
        before_tool_call=_approve_read if gate else None,
    )


def _suspended_before_read(echo_calls: list[str]) -> tuple[AgentState, RunState]:
    agent = _agent(echo_calls, gate=True)
    run = agent.start(max_steps=3, messages=[UserMessage(content="Count")])
    assert run.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
    assert run.wait_for_idle(5)
    captured = run.capture()
    return captured.agent_state, captured.run_state


def _saved_result(state: RunState, call_id: str) -> ToolResultMessage:
    result = state.steps[0].tools[call_id].result
    assert result is not None
    return result


@pytest.mark.parametrize("restored", [False, True])
def test_a_program_reads_an_earlier_program_of_the_same_step(restored: bool) -> None:
    echo_calls: list[str] = []
    if restored:
        history, saved = _suspended_before_read(echo_calls)
        run = _agent(echo_calls, gate=True, state=history).resume(saved)
        run.submit(
            HumanToolAnswer(request_id="run-read", decision=InputDecision.APPROVE)
        )
    else:
        run = _agent(echo_calls, gate=False).start(
            max_steps=3, messages=[UserMessage(content="Count")]
        )
    output = run.result(timeout=10).output.text
    assert run.wait_for_idle(5)
    assert "Execution completed" in output
    assert "Output:\n2" in output


def test_a_program_saved_while_running_is_not_run_again_on_restore() -> None:
    """The runtime can resume a run whose owner was lost while a program ran.

    Chat saves checkpoints only at idle suspension, so this state comes from
    another runtime caller. A program's calls can have effects, so it never runs
    twice.
    """
    echo_calls: list[str] = []
    history, saved = _suspended_before_read(echo_calls)
    # Built by hand: the owner was lost while the program ran, so no answer is
    # pending any more.
    assert saved.progress is not None
    saved.progress.pending_tool_calls = {}
    assert saved.steps[0].tools[READ.id].status == ExecutionStatus.RUNNING

    events: list[AgentEvent] = []
    agent = _agent(echo_calls, gate=True, state=history)
    run = agent.resume(saved, on_event=events.append)
    output = run.result(timeout=10).output.text
    assert run.wait_for_idle(5)

    assert echo_calls == []
    assert output == RESTORED_RUNNING_MESSAGE
    snapshot = run.snapshot()
    assert snapshot.steps[0].tools[READ.id].status == ExecutionStatus.ERROR
    saved_result = _saved_result(snapshot, READ.id)
    assert (saved_result.is_error, saved_result.details) == (True, None)
    assert any(
        isinstance(event, ToolEndEvent) and event.tool_call.id == READ.id
        for event in events
    )


EARLIER_TURN: list[Message] = [
    UserMessage(id="question", content="Remember a value"),
    AssistantMessage(
        id="store-call",
        content=[
            ToolCall(id="store", name=CodeModeTool.NAME, arguments={"code": "..."})
        ],
    ),
    ToolResultMessage(
        id="store-result",
        tool_call_id="store",
        tool_name=CodeModeTool.NAME,
        content="Stored: k.",
        details=CodeModeExecutionResult(
            cell_id=1,
            code="store('k', 'kept')",
            status="completed",
            commit=StoreCommit(ordinal=1, follows=0, writes={"k": "kept"}),
        ),
    ),
    AssistantMessage(id="answer", content=[TextContent(text="Saved.")]),
]


def _load_in_new_turn(
    history: list[Message], checkpoint: CompactionCheckpoint | None
) -> tuple[str, list[GenerationRequest]]:
    requests: list[GenerationRequest] = []

    def reply(request: GenerationRequest, _: CancellationSignal) -> AssistantMessage:
        requests.append(request)
        if len(requests) == 1:
            return AssistantMessage(
                content=[
                    ToolCall(
                        id="load",
                        name=CodeModeTool.NAME,
                        arguments={"code": "load('k')"},
                    )
                ]
            )
        return AssistantMessage(content=[TextContent(text="Done.")])

    agent = Agent(
        FakeModelClient(reply),
        tools=[
            CodeModeTool([EchoTool()], cells=CodeCells(), limits=SandboxLimits()).bind(
                ToolContext
            )
        ],
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        state=AgentState(messages=history, checkpoint=checkpoint),
    )
    run = agent.start(max_steps=2, messages=[UserMessage(content="Load it")])
    run.result()
    assert run.wait_for_idle(timeout=5)
    loaded = next(
        message
        for message in requests[-1].messages
        if isinstance(message, ToolResultMessage) and message.tool_call_id == "load"
    )
    assert isinstance(loaded.details, CodeModeExecutionResult)
    return loaded.details.result or "", requests


def test_store_keeps_values_written_before_the_compaction_boundary() -> None:
    checkpoint = CompactionCheckpoint(
        summary="The user saved a value.", covered_through_message_id="answer"
    )
    value, requests = _load_in_new_turn(EARLIER_TURN, checkpoint)
    assert value == "'kept'"
    # The model does not see the compacted store call.
    assert not any(
        isinstance(message, ToolResultMessage) for message in requests[0].messages
    )


def test_a_running_cell_stops_with_a_closing_record_when_the_run_suspends() -> None:
    release_child = threading.Event()

    def child_generate(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        while not release_child.wait(0.01):
            signal.check()
        return AssistantMessage(content=[TextContent(text="child done")])

    def delegate(invocation: ToolInvocation) -> ChildRunWait:
        child = Agent(
            FakeModelClient(child_generate),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        )
        spawned = invocation.agents.spawn_agent(
            child, name="child", description="", messages=[], max_steps=1
        )
        return ChildRunWait(run_ids=[spawned.run_id])

    def generate(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(isinstance(message, ToolResultMessage) for message in request.messages):
            return AssistantMessage(content=[TextContent(text="answer")])
        return AssistantMessage(
            content=[
                ToolCall(
                    id="loop",
                    name=CodeModeTool.NAME,
                    arguments={"code": "yield_control()\nwhile True:\n    pass\n"},
                ),
                ToolCall(id="delegate", name="delegate", arguments={}),
            ]
        )

    cells = CodeCells()
    tool = CodeModeTool([], cells=cells, limits=LIMITS)
    parent = Agent(
        FakeModelClient(generate),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        tools=[
            tool.bind(ToolContext),
            AgentTool(
                definition=ToolDefinition(
                    name="delegate", description="", parameters={}
                ),
                execute=delegate,
                result_from_children=lambda *_: ToolResult(content="delegated"),
            ),
        ],
        on_finish=cells.finish,
        on_suspend=cells.suspend,
    )
    coordinator = AgentCoordinator()
    run = parent.start(max_steps=2, coordinator=coordinator)
    try:
        assert run.wait_until_settled(timeout=10).status == RunStatus.SUSPENDED
        assert run.wait_for_idle(5)
        # The cell stopped instead of running while nothing owns the run.
        assert cells._cells[1]._end is not None
        details = _saved_result(run.capture().run_state, "loop").details
        assert isinstance(details, CodeModeExecutionResult)
        assert details.closing is not None
        assert details.closing.reason == "suspended"
        assert details.closing.status == "terminated"
    finally:
        release_child.set()
    assert run.result().output.text == "answer"
    assert coordinator.close(timeout=3)


def test_before_tool_call_denies_direct_and_program_calls_alike() -> None:
    ran: list[str] = []

    def secret(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        ran.append(invocation.call_id)
        return ToolResult(content="secret value")

    secret_tool = FakeTool("secret", secret)
    code_mode = CodeModeTool(
        [secret_tool, FakeTool("echo", lambda _i, _c: ToolResult(content="echoed"))],
        cells=CodeCells(),
        limits=LIMITS,
    )
    program = ToolCall(
        id="program",
        name=CodeModeTool.NAME,
        arguments={
            "code": "print(await echo(value='x'))\n"
            "try:\n"
            "    await secret(value='y')\n"
            "except RuntimeError as error:\n"
            "    print('denied:', error)\n"
        },
    )
    direct = ToolCall(id="direct", name="secret", arguments={"value": "x"})

    def respond(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        if results:
            text = "\n".join(f"{m.tool_call_id}: {m.text}" for m in results)
            return AssistantMessage(content=[TextContent(text=text)])
        return AssistantMessage(content=[direct, program])

    def deny_secret(context: ToolCallContext) -> ToolResult | None:
        if context.call.name != "secret":
            return None
        return ToolResult(content="secret is blocked by policy", is_error=True)

    run = Agent(
        FakeModelClient(respond),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id="agent",
        tools=[code_mode.bind(ToolContext), secret_tool.bind(ToolContext)],
        before_tool_call=deny_secret,
    ).start(max_steps=3, messages=[UserMessage(content="Read the secret")])
    output = run.result(timeout=10).output.text
    assert run.wait_for_idle(5)
    assert "direct: secret is blocked by policy" in output
    assert "echoed\ndenied: secret is blocked by policy" in output
    assert ran == []


@pytest.mark.parametrize("program", [False, True], ids=["direct", "program"])
def test_a_raising_before_tool_call_fails_direct_and_program_calls_alike(
    program: bool,
) -> None:
    ran: list[str] = []

    def secret(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        ran.append(invocation.call_id)
        return ToolResult(content="secret value")

    secret_tool = FakeTool("secret", secret)
    cells = CodeCells()
    code_mode = CodeModeTool([secret_tool], cells=cells, limits=LIMITS)
    # The program cannot catch the policy failure and go on.
    call = (
        ToolCall(
            id="call",
            name=CodeModeTool.NAME,
            arguments={
                "code": "try:\n"
                "    await secret(value='y')\n"
                "except BaseException as error:\n"
                "    print('caught:', error)\n"
                "store('k', 'v')\n"
            },
        )
        if program
        else ToolCall(id="call", name="secret", arguments={"value": "x"})
    )

    def respond(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(isinstance(m, ToolResultMessage) for m in request.messages):
            return AssistantMessage(content=[TextContent(text="went on")])
        return AssistantMessage(content=[call])

    def policy(context: ToolCallContext) -> ToolResult | None:
        if context.call.name == "secret":
            raise RuntimeError("the policy service is unavailable")
        return None

    run = Agent(
        FakeModelClient(respond),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id="agent",
        tools=[code_mode.bind(ToolContext), secret_tool.bind(ToolContext)],
        before_tool_call=policy,
    ).start(max_steps=3, messages=[UserMessage(content="Read the secret")])
    with pytest.raises(RunFailed) as failed:
        run.result(timeout=10)
    assert failed.value.failure.kind == RunFailureKind.EXECUTION
    assert run.wait_for_idle(5)
    assert ran == []
    if program:
        cell = cells._cells[1]
        assert cell._end is not None and cell._end.status != "completed"
        assert cell._commit is None


def test_a_raising_before_tool_call_fails_the_run_when_no_one_watches_the_cell() -> (
    None
):
    hook_raised = threading.Event()
    cells = CodeCells()
    secret_tool = FakeTool("secret", lambda _i, _c: ToolResult(content="secret"))
    code_mode = CodeModeTool([secret_tool], cells=cells, limits=LIMITS)
    # The first observation ends at the yield; no wait_code call watches the
    # cell after that.
    call = ToolCall(
        id="call",
        name=CodeModeTool.NAME,
        arguments={"code": "yield_control()\nawait secret(value='y')\n"},
    )

    def respond(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        if any(isinstance(m, ToolResultMessage) for m in request.messages):
            assert hook_raised.wait(10)
            return AssistantMessage(content=[TextContent(text="went on")])
        return AssistantMessage(content=[call])

    def policy(context: ToolCallContext) -> ToolResult | None:
        if context.call.name == "secret":
            hook_raised.set()
            raise RuntimeError("the policy service is unavailable")
        return None

    run = Agent(
        FakeModelClient(respond),
        generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
        agent_id="agent",
        tools=[code_mode.bind(ToolContext)],
        before_tool_call=policy,
        on_finish=cells.finish,
        on_suspend=cells.suspend,
    ).start(max_steps=3, messages=[UserMessage(content="Read the secret")])
    with pytest.raises(RunFailed) as failed:
        run.result(timeout=10)
    assert failed.value.failure.kind == RunFailureKind.EXECUTION
    assert run.wait_for_idle(5)
    # The cell's closing record is still saved.
    details = _saved_result(run.capture().run_state, "call").details
    assert isinstance(details, CodeModeExecutionResult)
    assert details.closing is not None
    assert [(c.function_name, c.state) for c in details.closing.calls] == [
        ("secret", "error")
    ]
