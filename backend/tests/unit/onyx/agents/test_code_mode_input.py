"""Code mode programs whose calls wait for the user's input: the program parks,
the run saves it, and any process continues it after the answer."""

import gc
import json
import sys
import threading
import time
from collections.abc import Callable, Mapping

import pydantic_monty
import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.events import AgentEvent, InputEndedEvent, InputRequiredEvent
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    RunState,
    RunStatus,
    ToolCallContext,
)
from onyx.agents.runtime import Agent, RestorableFeature, Run
from onyx.agents.tool_execution import UNAVAILABLE_CALL_MESSAGE
from onyx.agents.tools import (
    HumanToolAnswer,
    InputDecision,
    InputMode,
    NestedInputWait,
    PendingToolInput,
    ToolInvocation,
    ToolOutcome,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.interfaces import GenerationContext
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.code_mode import sandbox
from onyx.tools.tool_implementations.code_mode import store as store_module
from onyx.tools.tool_implementations.code_mode.cells import (
    PARK_REFUSED_MESSAGE,
    PROGRAM_VERSION_MESSAGE,
    CodeCells,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
)
from onyx.tools.tool_implementations.code_mode.models import SavedCodeCell
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import LIMITS, FakeTool

# The default memory limit: a dump fits within its share of it.
PARKING_LIMITS = LIMITS.model_copy(update={"max_memory_bytes": 128 * 1024 * 1024})
PROGRAM = 'print("before")\nr = await tools.send(value="x")\nprint("sent", r)'
REQUEST_ID = "send-approval"


class SavedCells(BaseModel):
    cells: list[SavedCodeCell]


class CellsFeature(RestorableFeature):
    """Saves and restores the cells of one agent, as chat's feature does."""

    def __init__(self, cells: CodeCells) -> None:
        self.cells = cells

    def capture_state(self) -> SavedCells:
        return SavedCells(cells=self.cells.saved())

    def restore_state(self, state: Mapping[str, JsonValue]) -> None:
        self.cells.restore(SavedCells.model_validate(state).cells)


def _ask_for_send(context: ToolCallContext) -> PendingToolInput | None:
    if context.call.name != "send":
        return None
    return PendingToolInput(
        request_id=REQUEST_ID, prompt="Send?", mode=InputMode.EXECUTE
    )


def _reply(
    steps: tuple[ToolCall, ...], shown: threading.Event
) -> Callable[[GenerationRequest, CancellationSignal], AssistantMessage]:
    """Makes `steps` one call per step, then answers with the last result.
    Steps after the first wait until a request shows."""

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        if len(results) < len(steps):
            assert not results or shown.wait(10)
            return AssistantMessage(content=[steps[len(results)]])
        return AssistantMessage(content=[TextContent(text=results[-1].text)])

    return reply


class Agents:
    """Builds the agent of one process; each gets fresh cells and tools."""

    def __init__(
        self, *steps: ToolCall, parameters: dict[str, JsonValue] | None = None
    ) -> None:
        self.steps = steps
        self.sent: list[JsonValue] = []
        self.parameters = parameters
        # Builds agents without the `send` tool, as after its server is removed.
        self.send_removed = False
        self.gate: threading.Event | None = None
        # Set once a request shows; later model steps wait for it.
        self.shown = threading.Event()

    def send(self, invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        self.sent.append(invocation.arguments["value"])
        return ToolResult(content=json.dumps({"sent": invocation.arguments["value"]}))

    def wait(self, invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        assert self.gate is not None and self.gate.wait(10)
        return ToolResult(content=json.dumps({"waited": invocation.arguments["value"]}))

    def agent(self, state: AgentState | None = None) -> Agent:
        cells = CodeCells()
        tools: list[Tool] = [
            *(
                []
                if self.send_removed
                else [FakeTool("send", self.send, parameters=self.parameters)]
            ),
            FakeTool("wait", self.wait),
        ]
        execute = CodeModeTool(tools, cells=cells, limits=PARKING_LIMITS)
        return Agent(
            FakeModelClient(_reply(self.steps, self.shown)),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id="agent",
            state=state,
            tools=[
                execute.bind(ToolContext),
                WaitCodeTool(cells, execute.program).bind(ToolContext),
            ],
            before_tool_call=_ask_for_send,
            on_suspend=cells.suspend,
            on_finish=cells.finish,
            restoration=CellsFeature(cells),
        )


def _execute(call_id: str, code: str, yield_ms: int = 10_000) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=CodeModeTool.NAME,
        arguments={"code": code, "yield_time_ms": yield_ms},
    )


def _suspended(run: Run) -> RunState:
    state = run.wait_until_settled(timeout=20)
    assert state.status == RunStatus.SUSPENDED, state.failure
    assert run.wait_for_idle(10)
    return state


def _transferred(run: Run) -> ExecutionCheckpoint:
    """The suspended run as another process loads it."""
    return ExecutionCheckpoint.model_validate(run.capture().model_dump(mode="json"))


def _answer(decision: InputDecision) -> HumanToolAnswer:
    return HumanToolAnswer(
        request_id=REQUEST_ID,
        decision=decision,
        result=ToolResult(content="rejected", is_error=True)
        if decision == InputDecision.DENY
        else None,
    )


@pytest.mark.parametrize("approved", [True, False], ids=["approved", "rejected"])
def test_a_program_parks_and_another_agent_continues_it(approved: bool) -> None:
    agents = Agents(_execute("program", PROGRAM))
    events: list[AgentEvent] = []
    run = agents.agent().start(
        max_steps=3, messages=[UserMessage(content="Send")], on_event=events.append
    )
    saved = _suspended(run)

    assert saved.progress is not None
    pending = saved.progress.pending_tool_calls["program"]
    assert isinstance(pending, NestedInputWait)
    [shown] = [event for event in events if isinstance(event, InputRequiredEvent)]
    assert (shown.tool_call.id, shown.nested_call) == (
        "program",
        ToolCall(id="program:0", name="send", arguments={"value": "x"}),
    )
    assert agents.sent == []

    checkpoint = _transferred(run)
    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state,
        answers=[_answer(InputDecision.APPROVE if approved else InputDecision.DENY)],
    )
    output = resumed.result(timeout=20).output.text
    assert resumed.wait_for_idle(10)

    assert "before" in output
    if approved:
        assert agents.sent == ["x"]
        assert "sent {'sent': 'x'}" in output
    else:
        assert agents.sent == []
        assert "rejected" in output


def test_parking_waits_for_a_running_call_of_the_program() -> None:
    agents = Agents(
        _execute(
            "program",
            'a, b = await asyncio.gather(tools.wait(value="a"), tools.send(value="b"))\nprint(a, b)',
        )
    )
    agents.gate = threading.Event()
    shown = threading.Event()
    run = agents.agent().start(
        max_steps=3,
        messages=[UserMessage(content="Send")],
        on_event=lambda event: (
            shown.set() if isinstance(event, InputRequiredEvent) else None
        ),
    )
    try:
        # The card shows at once, while the other call runs.
        assert shown.wait(10)
        assert run.status == RunStatus.RUNNING
        agents.gate.set()
        _suspended(run)

        run.submit(_answer(InputDecision.APPROVE))
        output = run.result(timeout=20).output.text
        assert "{'waited': 'a'} {'sent': 'b'}" in output
    finally:
        agents.gate.set()
        run.cancel()
        assert run.wait_for_idle(10)


def test_a_background_cell_shows_its_request_before_the_model_waits() -> None:
    agents = Agents(
        _execute("program", f"yield_control()\n{PROGRAM}", yield_ms=1_000),
        ToolCall(id="wait", name=WaitCodeTool.NAME, arguments={"cell_id": 1}),
    )
    events: list[AgentEvent] = []

    def on_event(event: AgentEvent) -> None:
        events.append(event)
        if isinstance(event, InputRequiredEvent):
            agents.shown.set()

    run = agents.agent().start(
        max_steps=4, messages=[UserMessage(content="Send")], on_event=on_event
    )
    saved = _suspended(run)

    assert saved.progress is not None
    assert isinstance(saved.progress.pending_tool_calls["wait"], NestedInputWait)
    shown = [event for event in events if isinstance(event, InputRequiredEvent)]
    # Shown once, at the cell's execute_code call, before wait_code saved it.
    assert [event.tool_call.id for event in shown] == ["program"]

    run.submit(_answer(InputDecision.APPROVE))
    output = run.result(timeout=20).output.text
    assert run.wait_for_idle(10)
    assert agents.sent == ["x"]
    assert "sent {'sent': 'x'}" in output


def test_a_program_too_large_to_park_continues_without_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Any growth of the worker is over this share, so the dump is refused.
    monkeypatch.setattr(sandbox, "MAX_DUMP_MEMORY_SHARE", -1)
    agents = Agents(
        _execute(
            "program",
            'try:\n    await tools.send(value="x")\nexcept RuntimeError as error:\n'
            '    print("failed:", error)',
        )
    )
    events: list[AgentEvent] = []
    run = agents.agent().start(
        max_steps=3, messages=[UserMessage(content="Send")], on_event=events.append
    )
    output = run.result(timeout=20).output.text
    assert run.wait_for_idle(10)

    assert agents.sent == []
    assert PARK_REFUSED_MESSAGE.format(name="send") in output
    ended = [event for event in events if isinstance(event, InputEndedEvent)]
    assert [(event.request.request_id, event.answer) for event in ended] == [
        (REQUEST_ID, None)
    ]


@pytest.mark.parametrize("change", ["parameters", "removed"])
def test_a_restored_call_whose_tool_changed_does_not_run(change: str) -> None:
    agents = Agents(_execute("program", PROGRAM))
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    _suspended(run)
    checkpoint = _transferred(run)

    if change == "removed":
        agents.send_removed = True
    else:
        agents.parameters = {
            "type": "object",
            "properties": {"other": {"type": "string"}},
        }
    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state, answers=[_answer(InputDecision.APPROVE)]
    )
    output = resumed.result(timeout=20).output.text
    assert resumed.wait_for_idle(10)

    assert agents.sent == []
    assert UNAVAILABLE_CALL_MESSAGE in output


def test_a_run_that_ends_while_its_program_waits_closes_the_cell() -> None:
    agents = Agents(_execute("program", PROGRAM))
    events: list[AgentEvent] = []
    run = agents.agent().start(
        max_steps=3, messages=[UserMessage(content="Send")], on_event=events.append
    )
    _suspended(run)

    run.cancel()
    assert run.wait_for_idle(10)

    snapshot = run.snapshot()
    assert snapshot.status == RunStatus.CANCELLED
    result = snapshot.steps[0].tools["program"].result
    assert result is not None and "before" in result.text
    assert agents.sent == []
    ended = [event for event in events if isinstance(event, InputEndedEvent)]
    assert [(event.request.request_id, event.answer) for event in ended] == [
        (REQUEST_ID, None)
    ]


def test_a_program_parked_by_another_monty_version_stops_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agents = Agents(_execute("program", PROGRAM))
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    _suspended(run)
    checkpoint = _transferred(run)

    monkeypatch.setattr(pydantic_monty, "__version__", "0.0.0-other")
    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state, answers=[_answer(InputDecision.APPROVE)]
    )
    output = resumed.result(timeout=20).output.text
    assert resumed.wait_for_idle(10)

    assert agents.sent == []
    assert PROGRAM_VERSION_MESSAGE in output


def test_a_park_that_runs_out_of_memory_stops_the_program_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The worker's memory reads low, so the dump runs and exceeds the limit.
    monkeypatch.setattr(sandbox, "_worker_memory_bytes", lambda _pid: 0)
    agents = Agents(_execute("program", f"big = 'x' * (39 * 1024 * 1024)\n{PROGRAM}"))
    events: list[AgentEvent] = []
    run = agents.agent().start(
        max_steps=3, messages=[UserMessage(content="Send")], on_event=events.append
    )
    output = run.result(timeout=30).output.text
    assert run.wait_for_idle(10)

    assert agents.sent == []
    assert sandbox.PARK_MEMORY_MESSAGE in output
    ended = [event for event in events if isinstance(event, InputEndedEvent)]
    assert [(event.request.request_id, event.answer) for event in ended] == [
        (REQUEST_ID, None)
    ]


def test_a_restored_run_that_ends_before_its_answer_closes_the_saved_cell() -> None:
    agents = Agents(_execute("program", PROGRAM))
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    _suspended(run)
    checkpoint = _transferred(run)
    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state, answers=[]
    )
    _suspended(resumed)

    resumed.cancel()
    assert resumed.wait_for_idle(10)

    snapshot = resumed.snapshot()
    assert snapshot.status == RunStatus.CANCELLED
    # The same record as when the run that parked the program ends.
    result = snapshot.steps[0].tools["program"].result
    assert result is not None and result.is_error
    assert "before" in result.text and "[0] send: unfinished" in result.text
    assert agents.sent == []


def test_a_restored_call_whose_function_now_names_another_tool_does_not_run() -> None:
    """`send-mail` and `send_mail` share the identifier `send_mail`; the first
    keeps it. With `send-mail` gone, `send_mail` names the other tool, whose
    parameters are the same; its approval does not carry over."""
    sent: list[str] = []

    def sender(name: str) -> FakeTool:
        def run(_invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
            sent.append(name)
            return ToolResult(content=json.dumps({"sent": name}))

        return FakeTool(name, run)

    def agent(names: list[str], state: AgentState | None = None) -> Agent:
        cells = CodeCells()
        execute = CodeModeTool(
            [sender(name) for name in names], cells=cells, limits=PARKING_LIMITS
        )
        return Agent(
            FakeModelClient(
                _reply(
                    (_execute("program", 'print(await tools.send_mail(value="x"))'),),
                    threading.Event(),
                )
            ),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id="agent",
            state=state,
            tools=[
                execute.bind(ToolContext),
                WaitCodeTool(cells, execute.program).bind(ToolContext),
            ],
            before_tool_call=lambda context: (
                PendingToolInput(
                    request_id=REQUEST_ID, prompt="Send?", mode=InputMode.EXECUTE
                )
                if context.call.name == "send-mail"
                else None
            ),
            on_suspend=cells.suspend,
            on_finish=cells.finish,
            restoration=CellsFeature(cells),
        )

    run = agent(["send-mail", "send_mail"]).start(
        max_steps=3, messages=[UserMessage(content="Send")]
    )
    _suspended(run)
    checkpoint = _transferred(run)
    resumed = agent(["send_mail"], checkpoint.agent_state).resume(
        checkpoint.run_state, answers=[_answer(InputDecision.APPROVE)]
    )
    output = resumed.result(timeout=20).output.text
    assert resumed.wait_for_idle(10)

    assert sent == []
    assert UNAVAILABLE_CALL_MESSAGE in output


def test_a_program_whose_dump_exceeds_the_budget_continues_without_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox, "suspended_bytes", sandbox._SuspendedBytes(0))
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.code_mode.cells.suspended_bytes",
        sandbox.suspended_bytes,
    )
    agents = Agents(
        _execute(
            "program",
            'try:\n    await tools.send(value="x")\nexcept RuntimeError as error:\n'
            '    print("failed:", error)',
        )
    )
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    output = run.result(timeout=20).output.text
    assert run.wait_for_idle(10)

    assert agents.sent == []
    assert PARK_REFUSED_MESSAGE.format(name="send") in output


def test_a_parked_dump_counts_against_the_budget_until_nothing_holds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limit = 256 * 1024 * 1024
    budget = sandbox._SuspendedBytes(limit)
    monkeypatch.setattr(sandbox, "suspended_bytes", budget)
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.code_mode.cells.suspended_bytes", budget
    )
    agents = Agents(_execute("program", PROGRAM))
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    _suspended(run)
    assert budget.free < limit

    run.cancel()
    assert run.wait_for_idle(10)
    del run
    gc.collect()
    assert budget.free == limit


def test_a_restored_store_applies_the_writes_that_shrink_it_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The program writes `n`, deletes `a`, then enlarges `n`. Its store fits
    at each step, but `n`'s final value with `a` still stored does not."""
    monkeypatch.setattr(store_module, "MAX_STORE_BYTES", 1_000)
    agents = Agents(
        _execute("first", 'store("a", "x" * 580)'),
        _execute(
            "program",
            'store("n", "x")\nstore("a", None)\nstore("n", "y" * 580)\n'
            f'{PROGRAM}\nprint(len(load("n")), load("a"))',
        ),
    )
    agents.shown.set()
    run = agents.agent().start(max_steps=4, messages=[UserMessage(content="Send")])
    _suspended(run)
    checkpoint = _transferred(run)

    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state, answers=[_answer(InputDecision.APPROVE)]
    )
    output = resumed.result(timeout=20).output.text
    assert resumed.wait_for_idle(10)

    assert agents.sent == ["x"]
    assert "580 None" in output


def test_a_suspended_program_parks_on_the_reservation_that_it_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The program gives up its worker while its call's approval request is
    being opened, and parks once the call waits for the answer. Its dump fits
    the budget once, and the park counts it once."""

    class OneDump(sandbox._SuspendedBytes):
        """A budget that holds exactly the first dump reserved."""

        def __init__(self) -> None:
            super().__init__(0)
            self.reservations = 0

        def reserve(self, size: int) -> bool:
            self.reservations += 1
            if self.reservations == 1:
                self.release(size)
            return super().reserve(size)

    budget = OneDump()
    monkeypatch.setattr(sandbox, "suspended_bytes", budget)
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.code_mode.cells.suspended_bytes", budget
    )
    monkeypatch.setattr(sandbox._worker_demand, "gives_up", lambda _wake: True)
    opening = threading.Event()
    ask = _ask_for_send

    def ask_when_opened(context: ToolCallContext) -> PendingToolInput | None:
        if context.call.name == "send":
            assert opening.wait(10)
        return ask(context)

    monkeypatch.setattr(sys.modules[__name__], "_ask_for_send", ask_when_opened)
    agents = Agents(_execute("program", PROGRAM))
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    try:
        deadline = time.monotonic() + 10
        while budget.reservations == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert budget.reservations == 1
        opening.set()
        _suspended(run)

        run.submit(_answer(InputDecision.APPROVE))
        output = run.result(timeout=20).output.text
        assert agents.sent == ["x"]
        assert "sent {'sent': 'x'}" in output
    finally:
        opening.set()
        run.cancel()
        assert run.wait_for_idle(10)


def test_a_restored_call_keeps_arguments_whose_names_collide() -> None:
    """`repo-name` and `repo_name` become the keywords `repo_name` and
    `repo_name_2`. After the park, the approved call gets both values."""
    received: list[JsonValue] = []

    def send(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        received.append(dict(invocation.arguments))
        return ToolResult(content=json.dumps({"sent": True}))

    def agent(state: AgentState | None = None) -> Agent:
        cells = CodeCells()
        tool = FakeTool(
            "send",
            send,
            parameters={
                "type": "object",
                "properties": {
                    "repo-name": {"type": "string"},
                    "repo_name": {"type": "string"},
                },
                "required": ["repo-name", "repo_name"],
            },
        )
        execute = CodeModeTool([tool], cells=cells, limits=PARKING_LIMITS)
        return Agent(
            FakeModelClient(
                _reply(
                    (
                        _execute(
                            "program",
                            'print(await tools.send(repo_name="A", repo_name_2="B"))',
                        ),
                    ),
                    threading.Event(),
                )
            ),
            generation_context=GenerationContext(flow=LLMFlow.CHAT_RESPONSE),
            agent_id="agent",
            state=state,
            tools=[
                execute.bind(ToolContext),
                WaitCodeTool(cells, execute.program).bind(ToolContext),
            ],
            before_tool_call=_ask_for_send,
            on_suspend=cells.suspend,
            on_finish=cells.finish,
            restoration=CellsFeature(cells),
        )

    run = agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    _suspended(run)
    checkpoint = _transferred(run)
    resumed = agent(checkpoint.agent_state).resume(
        checkpoint.run_state, answers=[_answer(InputDecision.APPROVE)]
    )
    resumed.result(timeout=20)
    assert resumed.wait_for_idle(10)

    assert received == [{"repo-name": "A", "repo_name": "B"}]


def test_a_park_whose_arguments_cannot_be_saved_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The saved copy of a call's keyword arguments has its own bound. A copy
    over it refuses the park, as a dump that does not fit does, and the dump's
    reservation ends."""
    limit = 256 * 1024 * 1024
    budget = sandbox._SuspendedBytes(limit)
    monkeypatch.setattr(sandbox, "suspended_bytes", budget)
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.code_mode.cells.suspended_bytes", budget
    )
    monkeypatch.setattr(
        "onyx.tools.tool_implementations.code_mode.cells.MAX_TOOL_ARGUMENT_BYTES", 1
    )
    agents = Agents(
        _execute(
            "program",
            'try:\n    await tools.send(value="x")\nexcept RuntimeError as error:\n'
            '    print("failed:", error)',
        )
    )
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    output = run.result(timeout=20).output.text
    assert run.wait_for_idle(10)

    assert agents.sent == []
    assert PARK_REFUSED_MESSAGE.format(name="send") in output
    assert budget.free == limit
