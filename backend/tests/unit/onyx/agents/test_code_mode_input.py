"""Code mode programs whose calls wait for the user's input: the program parks,
the run saves it, and any process continues it after the answer."""

import gc
import json
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pydantic_monty
import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.events import (
    AgentEvent,
    AgentSuspendedEvent,
    InputEndedEvent,
    InputRequiredEvent,
    ToolUpdateEvent,
)
from onyx.agents.models import (
    AgentState,
    ExecutionCheckpoint,
    RunState,
    RunStatus,
    ToolCallContext,
    ToolResultAmendment,
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
from onyx.chat.emitter import Emitter
from onyx.chat.models import ResponseReplayData
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.response import response_record
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
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    CodeModeStart,
    Packet,
    SectionEnd,
    ToolApprovalRequest,
    ToolApprovalResolved,
)
from onyx.tools.interface import Tool
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.code_mode import sandbox
from onyx.tools.tool_implementations.code_mode import store as store_module
from onyx.tools.tool_implementations.code_mode.cells import (
    MAX_OPEN_CELLS,
    PARK_REFUSED_MESSAGE,
    PROGRAM_VERSION_MESSAGE,
    CodeCells,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CellClosing,
    CodeModeExecutionResult,
    SavedCodeCell,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.agents.fakes import FakeModelClient
from tests.unit.onyx.tools.code_mode.fakes import LIMITS, FakeTool, until

# The default memory limit: a dump fits within its share of it.
PARKING_LIMITS = LIMITS.model_copy(update={"max_memory_bytes": 128 * 1024 * 1024})
PROGRAM = 'print("before")\nr = await tools.send(value="x")\nprint("sent", r)'
REQUEST_ID = "send-approval"
# A cell that keeps running in the background until the test opens the gate.
BACKGROUND = 'yield_control()\nr = await tools.wait(value="b")\nprint("waited", r)'
# A cell that asks for its own approval in the background.
BACKGROUND_SEND = 'yield_control()\nr = await tools.send(value="bg")\nprint("sent", r)'
BACKGROUND_REQUEST_ID = "send-bg"
# A background cell that asks twice; the second request is an approval.
BACKGROUND_SEND_TWICE = (
    'yield_control()\nawait tools.send(value="bg")\n'
    'r = await tools.send(value="bg2")\nprint("sent", r)'
)
SECOND_BACKGROUND_REQUEST_ID = "send-bg2"
# A background cell whose second request opens once the "first" gate opens,
# and which parks once the "last" gate opens.
SPLIT_REQUESTS = (
    "async def later():\n"
    '    await tools.wait(value="first")\n'
    '    return await tools.send(value="bg2")\n'
    "yield_control()\n"
    "a, b, c = await asyncio.gather(\n"
    '    tools.send(value="bg"), later(), tools.wait(value="last")\n'
    ")\n"
    'print("sent", a, b)'
)

Reply = Callable[[GenerationRequest, CancellationSignal], AssistantMessage]


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
    """Asks for each `send`; the value "bg" gets BACKGROUND_REQUEST_ID, and
    "bg2" an approval request with SECOND_BACKGROUND_REQUEST_ID."""
    if context.call.name != "send":
        return None
    value = context.call.arguments.get("value")
    return PendingToolInput(
        request_id=BACKGROUND_REQUEST_ID
        if value == "bg"
        else SECOND_BACKGROUND_REQUEST_ID
        if value == "bg2"
        else REQUEST_ID,
        prompt="Send?",
        mode=InputMode.EXECUTE,
        approval=value == "bg2",
    )


def _reply(steps: tuple[ToolCall, ...], shown: threading.Event) -> Reply:
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
        self,
        *steps: ToolCall,
        parameters: dict[str, JsonValue] | None = None,
        reply: Reply | None = None,
    ) -> None:
        self.steps = steps
        self.reply = reply
        self.sent: list[JsonValue] = []
        self.sent_once = threading.Event()
        self.parameters = parameters
        # Builds agents without the `send` tool, as after its server is removed.
        self.send_removed = False
        self.gate: threading.Event | None = None
        # Gates of `wait` calls by value; other values use `gate`.
        self.gates: dict[JsonValue, threading.Event] = {}
        self.limits = PARKING_LIMITS
        # Set once a request shows; later model steps wait for it.
        self.shown = threading.Event()

    def send(self, invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        self.sent.append(invocation.arguments["value"])
        self.sent_once.set()
        return ToolResult(content=json.dumps({"sent": invocation.arguments["value"]}))

    def wait(self, invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        """Returns once the gate opens; it stops when its cell stops, as a tool
        that checks its cancellation does."""
        gate = self.gates.get(invocation.arguments["value"], self.gate)
        assert gate is not None
        deadline = time.monotonic() + 10
        while not gate.wait(0.05):
            invocation.cancellation.check()
            assert time.monotonic() < deadline
        return ToolResult(content=json.dumps({"waited": invocation.arguments["value"]}))

    def stuck(self, invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        """Returns once the gate opens, whatever its cancellation."""
        assert self.gate is not None and self.gate.wait(10)
        return ToolResult(content=json.dumps({"stuck": invocation.arguments["value"]}))

    def agent(self, state: AgentState | None = None) -> Agent:
        cells = CodeCells()
        tools: list[Tool] = [
            *(
                []
                if self.send_removed
                else [FakeTool("send", self.send, parameters=self.parameters)]
            ),
            FakeTool("wait", self.wait),
            FakeTool("stuck", self.stuck),
        ]
        execute = CodeModeTool(tools, cells=cells, limits=self.limits)
        return Agent(
            FakeModelClient(self.reply or _reply(self.steps, self.shown)),
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


def _answer(decision: InputDecision, request_id: str = REQUEST_ID) -> HumanToolAnswer:
    return HumanToolAnswer(
        request_id=request_id,
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


def _one_call_per_step(*steps: ToolCall) -> Reply:
    """Makes `steps` one call per step, then answers with the last result."""

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        if len(results) < len(steps):
            return AssistantMessage(content=[steps[len(results)]])
        return AssistantMessage(content=[TextContent(text=results[-1].text)])

    return reply


def _read_cell(cell_id: int) -> ToolCall:
    return ToolCall(
        id="read",
        name=WaitCodeTool.NAME,
        arguments={"cell_id": cell_id, "yield_time_ms": 10_000},
    )


def _start_with_request(agents: Agents) -> tuple[Run, list[AgentEvent]]:
    """Start the run; return once the program's call waits for its request,
    after a check that the run does not suspend while the other cell runs."""
    suspended = threading.Event()
    events: list[AgentEvent] = []

    def on_event(event: AgentEvent) -> None:
        events.append(event)
        if isinstance(event, AgentSuspendedEvent):
            suspended.set()

    run = agents.agent().start(
        max_steps=5, messages=[UserMessage(content="Send")], on_event=on_event
    )
    until(lambda: "program" in _pending_calls(run))
    # Without the other cell, the run suspends at once from here.
    assert not suspended.wait(1)
    assert run.status != RunStatus.SUSPENDED
    return run, events


def _pending_calls(run: Run) -> set[str]:
    progress = run.snapshot().progress
    return set() if progress is None else set(progress.pending_tool_calls)


def _closing(state: RunState, call_id: str) -> CellClosing | None:
    """The closing record of `call_id`'s saved result, if any."""
    execution = state.steps[0].tools.get(call_id) if state.steps else None
    result = execution.result if execution is not None else None
    if result is None or not isinstance(result.details, CodeModeExecutionResult):
        return None
    return result.details.closing


def _closing_text(state: RunState, call_id: str) -> str:
    """The saved result of `call_id`, whose closing record ends it."""
    result = state.steps[0].tools[call_id].result
    assert result is not None
    assert isinstance(result.details, CodeModeExecutionResult)
    assert result.details.closing is not None
    return result.text


def test_a_cell_that_ends_while_a_request_waits_keeps_its_result() -> None:
    """The resident run; test_parked_program_handoff covers another process."""
    agents = Agents(
        reply=_one_call_per_step(
            _execute("background", BACKGROUND),
            _execute("program", PROGRAM),
            _read_cell(1),
        )
    )
    agents.gate = threading.Event()
    try:
        run, _events = _start_with_request(agents)
        agents.gate.set()
        saved = _suspended(run)
    finally:
        agents.gate.set()

    # The cell's end is in the closing record of its saved observation.
    assert "waited {'waited': 'b'}" in _closing_text(saved, "background")
    run.submit(_answer(InputDecision.APPROVE))
    output = run.result(timeout=20).output.text
    assert run.wait_for_idle(10)

    assert agents.sent == ["x"]
    # wait_code points to that record.
    assert output == (
        "Cell 1 completed before the run paused; its output and result are in "
        "its earlier result."
    )


def test_an_answer_while_a_cell_runs_continues_without_suspending() -> None:
    agents = Agents(
        reply=_one_call_per_step(
            _execute("background", BACKGROUND),
            _execute("program", PROGRAM),
            _read_cell(1),
        )
    )
    agents.gate = threading.Event()
    try:
        run, events = _start_with_request(agents)
        run.submit(_answer(InputDecision.APPROVE))
        # The approved call runs while the other cell still runs.
        assert agents.sent_once.wait(10)
        agents.gate.set()
        output = run.result(timeout=20).output.text
    finally:
        agents.gate.set()
    assert run.wait_for_idle(10)

    assert not any(isinstance(event, AgentSuspendedEvent) for event in events)
    assert agents.sent == ["x"]
    assert "Execution completed in cell 1" in output
    assert "waited {'waited': 'b'}" in output


def test_stop_while_a_cell_runs_ends_the_run_and_its_cells() -> None:
    agents = Agents(
        reply=_one_call_per_step(
            _execute("background", "yield_control()\nawait asyncio.sleep(60)"),
            _execute("program", PROGRAM),
        )
    )
    run, events = _start_with_request(agents)

    run.cancel()
    state = run.wait_until_settled(timeout=10)
    assert run.wait_for_idle(10)

    assert state.status == RunStatus.CANCELLED
    assert not any(isinstance(event, AgentSuspendedEvent) for event in events)
    assert agents.sent == []
    result = state.steps[0].tools["background"].result
    assert result is not None
    assert isinstance(result.details, CodeModeExecutionResult)
    closing = result.details.closing
    assert closing is not None
    assert (closing.reason, closing.status) == ("response_ended", "cancelled")


def test_a_call_that_outlives_its_program_does_not_hold_the_run() -> None:
    """The background cell ends at its time limit while its call ignores the
    cancellation. The run then pauses for the other request; the call only
    delays the drain."""
    agents = Agents(
        reply=_one_call_per_step(
            _execute("background", 'yield_control()\nawait tools.stuck(value="s")'),
            _execute("program", PROGRAM),
            _read_cell(1),
        )
    )
    agents.limits = PARKING_LIMITS.model_copy(update={"lifetime_seconds": 1})
    agents.gate = threading.Event()
    try:
        run = agents.agent().start(max_steps=5, messages=[UserMessage(content="Send")])
        # The pause closes the cell while its call still runs.
        until(lambda: _closing(run.snapshot(), "background") is not None)
        closing = _closing(run.snapshot(), "background")
        assert closing is not None and closing.status == "timed_out"
        assert run.snapshot().failure is None
    finally:
        agents.gate.set()
    _suspended(run)

    run.submit(_answer(InputDecision.APPROVE))
    output = run.result(timeout=20).output.text
    assert run.wait_for_idle(10)
    assert run.status == RunStatus.COMPLETE
    assert agents.sent == ["x"]
    assert output.startswith("Cell 1 timed out before the run paused;"), output


def _background_send_agents() -> Agents:
    """A background cell that asks to send "bg", then a program that asks to
    send "x", then a read of the background cell."""
    return Agents(
        reply=_one_call_per_step(
            _execute("background", BACKGROUND_SEND),
            _execute("program", PROGRAM),
            _read_cell(1),
        )
    )


def test_a_background_cell_keeps_its_request_across_a_handoff() -> None:
    """The background cell saves without an observer, the parked program with
    one; another process runs both approved calls."""
    agents = _background_send_agents()
    run = agents.agent().start(max_steps=5, messages=[UserMessage(content="Send")])
    _suspended(run)
    checkpoint = _transferred(run)
    assert checkpoint.run_state.progress is not None
    cells = SavedCells.model_validate(checkpoint.run_state.progress.feature_state)
    assert {cell.cell_id: cell.observer is None for cell in cells.cells} == {
        1: True,
        2: False,
    }

    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state,
        answers=[
            _answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID),
            _answer(InputDecision.APPROVE),
        ],
    )
    resumed.result(timeout=20)
    assert resumed.wait_for_idle(10)

    assert set(agents.sent) == {"bg", "x"} and len(agents.sent) == 2


def test_a_background_cell_continues_once_its_request_has_an_answer() -> None:
    """The background cell's answer arrives first: the cell continues in the
    resident run, which pauses again for the other request."""
    agents = _background_send_agents()
    events: list[AgentEvent] = []
    run = agents.agent().start(
        max_steps=5, messages=[UserMessage(content="Send")], on_event=events.append
    )
    _suspended(run)

    run.submit(_answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID))
    until(lambda: agents.sent_once.is_set() and run.status == RunStatus.SUSPENDED)
    saved = _suspended(run)

    assert agents.sent == ["bg"]
    ended = [event for event in events if isinstance(event, InputEndedEvent)]
    assert [event.request.request_id for event in ended] == [BACKGROUND_REQUEST_ID]
    assert "sent {'sent': 'bg'}" in _closing_text(saved, "background")

    run.submit(_answer(InputDecision.APPROVE))
    output = run.result(timeout=20).output.text
    assert run.wait_for_idle(10)
    assert agents.sent == ["bg", "x"]
    assert output == (
        "Cell 1 completed before the run paused; its output and result are in "
        "its earlier result."
    )


def test_an_answer_before_a_background_program_parks_still_runs_its_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user approves while another call of the background program runs,
    so the program has not parked yet. Once it parks, the approved call runs
    in the same step."""
    offers: list[int] = []
    continue_open = CodeCells.continue_open

    def counted(self: CodeCells, *args: Any, **kwargs: Any) -> list[str]:
        taken = continue_open(self, *args, **kwargs)
        offers.append(len(taken))
        return taken

    monkeypatch.setattr(CodeCells, "continue_open", counted)
    agents = Agents(
        reply=_one_call_per_step(
            _execute(
                "background",
                "yield_control()\n"
                'a, b = await asyncio.gather(tools.wait(value="a"), tools.send(value="bg"))\n'
                'print("sent", a, b)',
            ),
            _execute("program", PROGRAM),
        )
    )
    agents.gate = threading.Event()
    run = agents.agent().start(max_steps=5, messages=[UserMessage(content="Send")])
    try:
        until(lambda: "program" in _pending_calls(run))
        run.submit(_answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID))
        # Offered before the park, so the program took nothing.
        until(lambda: 0 in offers)
        agents.gate.set()
        saved = _suspended(run)

        assert agents.sent == ["bg"]
        assert saved.progress is not None
        assert saved.progress.step_index == 1
        assert list(saved.progress.pending_tool_calls) == ["program"]
    finally:
        agents.gate.set()
        run.cancel()
        assert run.wait_for_idle(10)


def _result(run: Run, step_index: int, call_id: str) -> ToolResultMessage | None:
    steps = run.snapshot().steps
    execution = (
        steps[step_index].tools.get(call_id) if len(steps) > step_index else None
    )
    return execution.result if execution is not None else None


@pytest.mark.parametrize("restored", [False, True], ids=["live", "restored"])
def test_a_background_cell_takes_the_answers_of_requests_from_each_observation(
    restored: bool,
) -> None:
    """The first request opens after the cell's first observation ends, the
    second while a wait_code call observes it, and the program parks after that
    observation ends. Both requests belong to the call that started the cell,
    so their answers continue the program together."""
    agents = Agents(
        reply=_one_call_per_step(
            _execute("background", SPLIT_REQUESTS),
            ToolCall(
                id="read",
                name=WaitCodeTool.NAME,
                arguments={"cell_id": 1, "yield_time_ms": 1_000},
            ),
            _execute("program", PROGRAM),
        )
    )
    first, last = threading.Event(), threading.Event()
    agents.gates = {"first": first, "last": last}

    def on_event(event: AgentEvent) -> None:
        # The wait_code call attached: it gets the cell's running calls.
        if isinstance(event, ToolUpdateEvent) and event.tool_call.id == "read":
            first.set()

    run = agents.agent().start(
        max_steps=5, messages=[UserMessage(content="Send")], on_event=on_event
    )
    try:
        until(
            lambda: (
                SECOND_BACKGROUND_REQUEST_ID
                in {request.request_id for request in run.pending_inputs}
            )
        )
        until(lambda: _result(run, 1, "read") is not None)
        last.set()
        _suspended(run)
        answers = [
            _answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID),
            _answer(InputDecision.APPROVE, SECOND_BACKGROUND_REQUEST_ID),
        ]
        if restored:
            checkpoint = _transferred(run)
            run = agents.agent(checkpoint.agent_state).resume(
                checkpoint.run_state, answers=answers
            )
        else:
            for answer in answers:
                run.submit(answer)
        until(lambda: sorted(map(str, agents.sent)) == ["bg", "bg2"])
        _suspended(run)
        run.submit(_answer(InputDecision.APPROVE))
        run.result(timeout=20)
        assert run.wait_for_idle(10)
        assert sorted(map(str, agents.sent)) == ["bg", "bg2", "x"]
    finally:
        first.set()
        last.set()
        run.cancel()
        assert run.wait_for_idle(10)


def test_a_program_that_parks_while_a_call_runs_takes_its_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The user approves while another call of the background program runs.
    Once the program parks, it takes the answer at once, while a direct call
    of the same step still runs."""
    offers: list[int] = []
    continue_open = CodeCells.continue_open

    def counted(self: CodeCells, *args: Any, **kwargs: Any) -> list[str]:
        taken = continue_open(self, *args, **kwargs)
        offers.append(len(taken))
        return taken

    monkeypatch.setattr(CodeCells, "continue_open", counted)
    agents = Agents(
        reply=_one_call_per_step(
            _execute(
                "background",
                "yield_control()\n"
                'a, b = await asyncio.gather(tools.wait(value="a"), tools.send(value="bg"))\n'
                'print("sent", a, b)',
            ),
            _execute("busy", 'print(await tools.wait(value="direct"))'),
        )
    )
    background, direct = threading.Event(), threading.Event()
    agents.gates = {"a": background, "direct": direct}
    run = agents.agent().start(max_steps=5, messages=[UserMessage(content="Send")])
    try:
        until(
            lambda: (
                BACKGROUND_REQUEST_ID
                in {request.request_id for request in run.pending_inputs}
            )
        )
        until(lambda: "busy" in run.snapshot().steps[-1].tools)
        run.submit(_answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID))
        # Offered before the park, so the program took nothing.
        until(lambda: 0 in offers)
        background.set()

        until(lambda: agents.sent == ["bg"])
        assert not direct.is_set()
        assert _result(run, 1, "busy") is None
    finally:
        background.set()
        direct.set()
        run.cancel()
        assert run.wait_for_idle(10)


def test_a_restored_background_cell_that_ends_unobserved_keeps_its_output() -> None:
    """The background cell continues in another process and ends there with no
    wait_code call: its closing record saves its output and store commit."""
    agents = Agents(
        reply=_one_call_per_step(
            _execute(
                "background",
                'yield_control()\nr = await tools.send(value="bg")\n'
                'store("k", "v")\nprint("sent", r)',
            ),
            _execute("program", PROGRAM),
        )
    )
    run = agents.agent().start(max_steps=5, messages=[UserMessage(content="Send")])
    _suspended(run)
    # As chat restores it in another process: the saved results keep their
    # typed details, which chat saves with the response.
    checkpoint = run.capture()
    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state,
        answers=[_answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID)],
    )
    try:
        until(lambda: agents.sent == ["bg"])
        state = _suspended(resumed)
    finally:
        resumed.cancel()
        assert resumed.wait_for_idle(10)

    closing = _closing(state, "background")
    assert closing is not None and closing.status == "completed"
    assert closing.commit is not None
    assert "sent {'sent': 'bg'}" in _closing_text(state, "background")


def test_a_saved_background_cell_stays_open_across_another_suspend() -> None:
    """A restored run suspends again before the background cell's answer: the
    cell stays saved, without an interrupted record, and continues later."""
    agents = _background_send_agents()
    run = agents.agent().start(max_steps=5, messages=[UserMessage(content="Send")])
    _suspended(run)
    # Typed result details, as chat restores them.
    checkpoint = run.capture()

    resumed = agents.agent(checkpoint.agent_state).resume(checkpoint.run_state)
    state = _suspended(resumed)
    assert _closing(state, "background") is None

    checkpoint = resumed.capture()
    last = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state,
        answers=[
            _answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID),
            _answer(InputDecision.APPROVE),
        ],
    )
    last.result(timeout=20)
    assert last.wait_for_idle(10)
    assert sorted(map(str, agents.sent)) == ["bg", "x"]


@pytest.mark.parametrize("late_wake", [False, True], ids=["wake", "late_wake"])
def test_a_program_that_parks_right_after_its_offer_takes_the_answer(
    monkeypatch: pytest.MonkeyPatch, late_wake: bool
) -> None:
    """The background program parks, and its driver ends, after the offer of
    its answer took nothing and before the tool phase checks for work. The
    run offers the answer again instead of suspending with it. With
    `late_wake`, the driver's wake waits for the run to start suspending:
    the run must not read the driver's end without its wake."""
    runs: list[Run] = []
    if late_wake:
        suspending = threading.Event()
        notify = Run.notify_tool_activity
        suspend = CodeCells.suspend

        def late_notify(self: Run) -> None:
            if threading.current_thread().name == "code-mode-cell-1":
                suspending.wait(2)
            notify(self)

        def marked_suspend(
            self: CodeCells, results: Sequence[ToolResultMessage]
        ) -> list[ToolResultAmendment]:
            suspending.set()
            return suspend(self, results)

        monkeypatch.setattr(Run, "notify_tool_activity", late_notify)
        monkeypatch.setattr(CodeCells, "suspend", marked_suspend)
    agents = Agents(
        reply=_one_call_per_step(
            _execute(
                "background",
                "yield_control()\n"
                'a, b = await asyncio.gather(tools.wait(value="a"), tools.send(value="bg"))\n'
                'print("sent", a, b)',
            ),
            _execute("program", PROGRAM),
        )
    )
    agents.gate = threading.Event()
    continue_open = CodeCells.continue_open

    def park_after_offer(self: CodeCells, *args: Any, **kwargs: Any) -> list[str]:
        taken = continue_open(self, *args, **kwargs)
        if not taken and agents.gate is not None and not agents.gate.is_set():
            agents.gate.set()
            until(lambda: runs[0].work.held.idle)
        return taken

    monkeypatch.setattr(CodeCells, "continue_open", park_after_offer)
    run = agents.agent().start(max_steps=5, messages=[UserMessage(content="Send")])
    runs.append(run)
    try:
        until(lambda: "program" in _pending_calls(run))
        run.submit(_answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID))
        saved = _suspended(run)

        assert agents.sent == ["bg"]
        assert saved.progress is not None
        assert saved.progress.open_inputs == {}
    finally:
        agents.gate.set()
        run.cancel()
        assert run.wait_for_idle(10)


def test_saved_cells_count_against_the_open_cell_limit() -> None:
    """Background cells that stay saved across steps are open cells."""
    agents = Agents(_execute("program", PROGRAM))
    run = agents.agent().start(max_steps=3, messages=[UserMessage(content="Send")])
    _suspended(run)
    progress = _transferred(run).run_state.progress
    assert progress is not None
    [saved] = SavedCells.model_validate(progress.feature_state).cells
    run.cancel()
    assert run.wait_for_idle(10)

    cells = CodeCells()
    cells.restore(
        [
            saved.model_copy(update={"cell_id": cell_id, "observer": None})
            for cell_id in range(1, MAX_OPEN_CELLS + 1)
        ]
    )
    execute = CodeModeTool([], cells=cells, limits=PARKING_LIMITS)
    refused = execute.run(
        ToolInvocation(
            call_id="next",
            arguments={"code": "1\n"},
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(refused, ToolResult) and refused.is_error
    assert "Open cells: 1, 2, 3, 4." in refused.content


def test_a_stopped_program_reports_its_request_end_once_the_run_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """wait_code stops a background program whose call waits for approval.
    The program's driver ends the request while the run ends; the run still
    reports that end. The approval gate's withdrawal holds the driver until
    the run ends, and the run's last step waits for the withdrawal to start."""
    withdrawing = threading.Event()
    withdrawn_after_run_end = threading.Event()

    class Approvals:
        def withdraw_approval(self, _request_id: str) -> None:
            withdrawing.set()
            run.wait_for_completion(10)
            withdrawn_after_run_end.set()

    approvals = Approvals()
    monkeypatch.setattr(Run, "approvals", property(lambda _self: approvals))
    steps = (
        _execute(
            "background",
            "yield_control()\n"
            'await asyncio.gather(tools.wait(value="a"), tools.send(value="bg2"))\n',
        ),
        ToolCall(
            id="stop",
            name=WaitCodeTool.NAME,
            arguments={"cell_id": 1, "terminate": True},
        ),
    )

    def reply(
        request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        results = [m for m in request.messages if isinstance(m, ToolResultMessage)]
        if not results:
            return AssistantMessage(content=[steps[0]])
        if len(results) == 1:
            assert agents.shown.wait(10)
            return AssistantMessage(content=[steps[1]])
        assert withdrawing.wait(10)
        return AssistantMessage(content=[TextContent(text="done")])

    agents = Agents(reply=reply)
    agents.gate = threading.Event()
    events: list[AgentEvent] = []

    def on_event(event: AgentEvent) -> None:
        events.append(event)
        if isinstance(event, InputRequiredEvent):
            agents.shown.set()

    run = agents.agent().start(
        max_steps=4, messages=[UserMessage(content="Send")], on_event=on_event
    )
    try:
        assert run.result(timeout=20).output.text == "done"
        assert run.wait_for_idle(10)
        assert withdrawn_after_run_end.is_set()
        assert [
            event.request.request_id
            for event in events
            if isinstance(event, InputEndedEvent)
        ] == [SECOND_BACKGROUND_REQUEST_ID]
        assert agents.sent == []
    finally:
        agents.gate.set()
        run.cancel()
        assert run.wait_for_idle(10)


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


def _second_request_agents() -> Agents:
    """A background cell that asks twice, then a program that asks to send
    "x", then a read of the background cell."""
    return Agents(
        reply=_one_call_per_step(
            _execute("background", BACKGROUND_SEND_TWICE),
            _execute("program", PROGRAM),
            _read_cell(1),
        )
    )


def _approval_cards(packets: list[Packet]) -> list[str]:
    return [
        packet.obj.approval_id
        for packet in packets
        if isinstance(packet.obj, ToolApprovalRequest)
    ]


def _placement(events: list[AgentEvent], request_id: str) -> tuple[str, int]:
    [event] = [
        event
        for event in events
        if isinstance(event, InputRequiredEvent)
        and event.request.request_id == request_id
    ]
    return event.message_id, event.step_index


def test_a_continued_background_program_shows_its_next_request_at_its_call() -> None:
    """The background cell continues in a later step, and its next request
    shows in the card of the call that started it."""
    agents = _second_request_agents()
    events: list[AgentEvent] = []
    packets: list[Packet] = []
    presenter = ResponsePresenter(Emitter(packets.append))

    def on_event(event: AgentEvent) -> None:
        events.append(event)
        presenter.consume(event)

    run = agents.agent().start(
        max_steps=5, messages=[UserMessage(content="Send")], on_event=on_event
    )
    try:
        _suspended(run)
        run.submit(_answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID))
        # Events arrive on the events worker.
        until(lambda: _approval_cards(packets) == [SECOND_BACKGROUND_REQUEST_ID])

        assert _placement(events, SECOND_BACKGROUND_REQUEST_ID) == _placement(
            events, BACKGROUND_REQUEST_ID
        )
    finally:
        run.cancel()
        assert run.wait_for_idle(10)


def test_a_resumed_background_program_shows_its_next_request_in_its_saved_card() -> (
    None
):
    """Another process replays the saved response first. The next request
    shows in the replayed card of the call that started the background cell,
    at the placement that the live stream gave that card."""
    agents = _second_request_agents()
    live: list[Packet] = []
    run = agents.agent().start(
        max_steps=5,
        messages=[UserMessage(content="Send")],
        on_event=ResponsePresenter(Emitter(live.append)).consume,
    )
    state = _suspended(run)
    checkpoint = _transferred(run)

    packets: list[Packet] = []
    presenter = ResponsePresenter(Emitter(packets.append))
    presenter.replay(
        response_record(state),
        ResponseReplayData(tools={}, documents={}, approvals={}),
        {},
    )
    replayed = len(packets)
    resumed = agents.agent(checkpoint.agent_state).resume(
        checkpoint.run_state,
        answers=[_answer(InputDecision.APPROVE, BACKGROUND_REQUEST_ID)],
        on_event=presenter.consume,
    )
    try:
        until(
            lambda: (
                SECOND_BACKGROUND_REQUEST_ID
                in {request.request_id for request in resumed.pending_inputs}
            )
        )
        resumed.submit(_answer(InputDecision.APPROVE, SECOND_BACKGROUND_REQUEST_ID))
        until(
            lambda: any(
                isinstance(packet.obj, ToolApprovalResolved) for packet in packets
            )
        )
    finally:
        resumed.cancel()
        assert resumed.wait_for_idle(10)

    card = _card_placement(live, BACKGROUND_SEND_TWICE)
    assert _card_placement(packets[:replayed], BACKGROUND_SEND_TWICE) == card
    later = packets[replayed:]
    assert [
        (packet.placement, packet.obj.approval_id)
        for packet in later
        if isinstance(packet.obj, ToolApprovalRequest)
    ] == [(card, SECOND_BACKGROUND_REQUEST_ID)]
    assert [
        (packet.placement, packet.obj.approval_id, packet.obj.outcome)
        for packet in later
        if isinstance(packet.obj, ToolApprovalResolved)
    ] == [(card, SECOND_BACKGROUND_REQUEST_ID, "approved")]
    # The ended card neither starts again nor ends again when the run ends.
    assert not [
        packet
        for packet in later
        if packet.placement == card
        and isinstance(packet.obj, (CodeModeStart, SectionEnd))
    ]


def _card_placement(packets: list[Packet], code: str) -> Placement:
    [placement] = [
        packet.placement
        for packet in packets
        if isinstance(packet.obj, CodeModeStart) and packet.obj.code == code
    ]
    return placement
