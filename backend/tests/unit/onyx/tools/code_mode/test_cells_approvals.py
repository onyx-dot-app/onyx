"""A program's call that waits for approval frees the cell's slot and stops with it."""

import threading
from concurrent.futures import CancelledError, Future

import pytest
from pydantic import JsonValue

from onyx.agents.tools import (
    InputMode,
    NestedCallGate,
    PendingToolInput,
    ToolInvocation,
    ToolOutcome,
)
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolCall, ToolResult
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.code_mode import cells as cells_module
from onyx.tools.tool_implementations.code_mode.cells import CodeCells
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
)
from onyx.tools.tool_implementations.code_mode.models import CodeModeExecutionResult
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.unit.onyx.tools.code_mode.fakes import LIMITS, FakeTool, until


class Program(NestedCallGate):
    """One response's code mode tools, where every `send` call waits for the
    test's answer, as a run's approval gate makes it."""

    def __init__(self) -> None:
        self.cells = CodeCells()
        self.sent: list[str] = []
        self.stopped_waits = 0
        self._lock = threading.Lock()
        self.waits: list[Future[ToolResult | None]] = []

        # `hold(value=...)` returns once the test sets this; no approval gates it.
        self.hold = threading.Event()

        def send(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
            self.sent.append(str(invocation.arguments["value"]))
            return ToolResult(content=f'"sent {invocation.arguments["value"]}"')

        def hold(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
            assert self.hold.wait(10)
            return ToolResult(content=f'"{invocation.arguments["value"]}"')

        self.execute = CodeModeTool(
            [FakeTool("send", send), FakeTool("hold", hold)],
            cells=self.cells,
            limits=LIMITS,
        )
        self.wait_tool = WaitCodeTool(self.cells)
        self.cancellation = CancellationSignal()

    def decide(self, call: ToolCall) -> PendingToolInput | None:
        return (
            PendingToolInput(
                request_id=call.id, prompt="Allow?", mode=InputMode.EXECUTE
            )
            if call.name == "send"
            else None
        )

    def wait_for_input(
        self,
        call: ToolCall,  # noqa: ARG002
        request: PendingToolInput,  # noqa: ARG002
        cancellation: CancellationSignal,
    ) -> ToolResult | None:
        waiter = Future[ToolResult | None]()
        with self._lock:
            self.waits.append(waiter)

        def stop_waiting() -> None:
            waiter.cancel()

        with cancellation.on_cancel(stop_waiting):
            try:
                return waiter.result(timeout=20)
            except CancelledError:
                with self._lock:
                    self.stopped_waits += 1
                cancellation.check()
                raise

    def approve(self, index: int) -> None:
        self.waits[index].set_result(None)

    def _invocation(self, arguments: dict[str, JsonValue]) -> ToolInvocation:
        return ToolInvocation(
            call_id="program",
            arguments=arguments,
            cancellation=self.cancellation,
            update=lambda _progress: None,
            nested_calls=self,
        )

    def start(self, code: str, yield_time_ms: int = 1_000) -> Future[ToolResult]:
        """Run `execute_code` on a thread: it does not return while a call waits."""

        def run() -> ToolResult:
            outcome = self.execute.run(
                self._invocation({"code": code, "yield_time_ms": yield_time_ms}),
                ToolContext(),
            )
            assert isinstance(outcome, ToolResult)
            return outcome

        return start_thread_future(run, name="test-program")

    def wait_code(
        self, cell_id: int = 1, terminate: bool = False
    ) -> CodeModeExecutionResult:
        outcome = self.wait_tool.run(
            self._invocation(
                {"cell_id": cell_id, "yield_time_ms": 5_000, "terminate": terminate}
            ),
            ToolContext(),
        )
        assert isinstance(outcome, ToolResult)
        assert isinstance(outcome.details, CodeModeExecutionResult), outcome.content
        return outcome.details

    def waiting(self, count: int) -> bool:
        with self._lock:
            return len(self.waits) == count


def _details(result: ToolResult) -> CodeModeExecutionResult:
    assert isinstance(result.details, CodeModeExecutionResult), result.content
    return result.details


def _running() -> int:
    return cells_module._running_cells._running


@pytest.fixture(autouse=True)
def one_running_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cells_module, "_running_cells", cells_module._RunningCells(1))


def test_a_waiting_call_frees_the_slot_and_takes_it_back_to_finish() -> None:
    program = Program()
    observed = program.start("print(await send(value='a'))\n")
    until(lambda: program.waiting(1))

    # Another program can run while the call waits.
    until(lambda: _running() == 0)
    other = program.start("print(1)\n")
    assert _details(other.result(timeout=10)).status == "completed"
    assert not observed.done()

    program.approve(0)

    finished = _details(observed.result(timeout=10))
    assert (finished.status, finished.stdout) == ("completed", "sent a\n")
    assert program.sent == ["a"]
    until(lambda: _running() == 0)


def test_an_approved_call_waits_for_a_free_slot_when_the_budget_is_full() -> None:
    program = Program()
    observed = program.start("print(await send(value='a'))\n", yield_time_ms=60_000)
    until(lambda: program.waiting(1))
    until(lambda: _running() == 0)
    # A second cell takes the only slot.
    blocker = program.start(
        "import asyncio\nyield_control()\nawait asyncio.sleep(30)\n"
    )
    assert _details(blocker.result(timeout=10)).status == "running"
    cell = program.cells._cells[1]

    program.approve(0)

    def approval_applied() -> bool:
        with cell._lock:
            return cell._awaiting_input == 0

    until(approval_applied)
    # The approved call does not run over the budget.
    assert (program.sent, _running()) == ([], 1)
    assert program.wait_code(cell_id=2, terminate=True).status == "terminated"

    finished = _details(observed.result(timeout=10))
    assert (finished.status, finished.stdout) == ("completed", "sent a\n")
    until(lambda: _running() == 0)


@pytest.mark.parametrize("ends", ["program_fails", "cell_terminated"])
def test_a_wait_stops_when_its_program_ends_and_the_tool_does_not_run(
    ends: str,
) -> None:
    program = Program()
    observed = program.start(
        "import asyncio\n"
        "async def fail():\n"
        "    await asyncio.sleep(0.5)\n"
        "    raise ValueError('boom')\n"
        "await asyncio.gather(send(value='a'), fail())\n"
        if ends == "program_fails"
        else "import asyncio\nyield_control()\nawait send(value='a')\n"
    )
    until(lambda: program.waiting(1))

    if ends == "program_fails":
        assert _details(observed.result(timeout=10)).status == "failed"
    else:
        assert _details(observed.result(timeout=10)).status == "running"
        assert program.wait_code(terminate=True).status == "terminated"

    until(lambda: program.stopped_waits == 1)
    assert program.sent == []
    until(lambda: _running() == 0)


def test_yield_control_ends_the_observation_while_a_call_waits() -> None:
    program = Program()
    observed = program.start(
        "import asyncio\n"
        "async def report():\n"
        "    await asyncio.sleep(0.3)\n"
        "    print('asked')\n"
        "    yield_control()\n"
        "result, _ = await asyncio.gather(send(value='a'), report())\n"
        "print(result)\n"
    )

    first = _details(observed.result(timeout=10))

    assert (first.status, first.stdout) == ("running", "asked\n")
    assert program.waiting(1)
    program.approve(0)
    final = program.wait_code()
    assert (final.status, final.stdout) == ("completed", "sent a\n")
