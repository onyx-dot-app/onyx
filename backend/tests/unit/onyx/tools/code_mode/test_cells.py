"""Cell lifecycle: yields, waits, termination, limits, store commits and closing records."""

import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from prometheus_client import REGISTRY
from pydantic import BaseModel, JsonValue

from onyx.agents.tools import (
    ToolExecutionMode,
    ToolInvocation,
    ToolOutcome,
    ToolProgress,
)
from onyx.context.search.models import SearchDocsResponse
from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.llm.models import Message, ToolResult, ToolResultMessage
from onyx.tools.models import ToolContext
from onyx.tools.tool_implementations.code_mode import cells as cells_module
from onyx.tools.tool_implementations.code_mode import store as store_module
from onyx.tools.tool_implementations.code_mode.cells import (
    MAX_OPEN_CELLS,
    CodeCell,
    CodeCells,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    DEFAULT_EXECUTE_YIELD_MS,
    CodeModeTool,
    WaitCodeTool,
)
from onyx.tools.tool_implementations.code_mode.models import (
    CodeModeCall,
    CodeModeCallFinished,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStdout,
    SandboxLimits,
    SandboxResult,
)
from onyx.tools.tool_implementations.code_mode.sandbox import BUSY_MESSAGE
from onyx.utils.threadpool_concurrency import start_thread_future
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.unit.onyx.tools.code_mode.fakes import (
    LIMITS,
    FakeTool,
    FakeWebSearchTool,
    echo,
    search,
    until,
)


class Response:
    """The code mode tools of one response, and its run cancellation."""

    def __init__(
        self, history: Sequence[Message] = (), limits: SandboxLimits = LIMITS
    ) -> None:
        self.cells = CodeCells()
        # `gate(value=...)` returns once the test opens the gate.
        self.gate = threading.Event()

        def gate(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
            assert self.gate.wait(10)
            return ToolResult(content=f'"{invocation.arguments["value"]}"')

        self.execute = CodeModeTool(
            [
                FakeTool("echo", echo),
                FakeTool("gate", gate),
                FakeTool("seq", gate, execution_mode=ToolExecutionMode.SEQUENTIAL),
                FakeWebSearchTool(search),
            ],
            cells=self.cells,
            limits=limits,
        )
        self.wait_tool = WaitCodeTool(self.cells)
        self.cancellation = CancellationSignal()
        self.recorded: list[Message] = list(history)
        self.events: dict[str, list[BaseModel]] = {}
        self._calls = 0

    def invocation(self, arguments: dict[str, JsonValue]) -> ToolInvocation:
        self._calls += 1
        call_id = f"call_{self._calls}"
        events = self.events.setdefault(call_id, [])

        def update(progress: ToolProgress) -> None:
            assert progress.details is not None
            events.append(progress.details)

        return ToolInvocation(
            call_id=call_id,
            arguments=arguments,
            cancellation=self.cancellation,
            update=update,
            recorded_results=[
                m for m in self.recorded if isinstance(m, ToolResultMessage)
            ],
        )

    def record(self, invocation: ToolInvocation, result: ToolResult) -> ToolResult:
        """Save a result in the response's messages, as the run does."""
        self.recorded.append(
            ToolResultMessage(
                tool_call_id=invocation.call_id,
                tool_name="execute_code",
                content=result.content,
                details=result.details,
                is_error=result.is_error,
            )
        )
        return result

    def run(
        self,
        code: str,
        yield_time_ms: int | None = None,
        context: ToolContext | None = None,
    ) -> ToolResult:
        arguments: dict[str, JsonValue] = {"code": code}
        if yield_time_ms is not None:
            arguments["yield_time_ms"] = yield_time_ms
        invocation = self.invocation(arguments)
        outcome = self.execute.run(invocation, context or ToolContext())
        assert isinstance(outcome, ToolResult)
        return self.record(invocation, outcome)

    def wait(
        self, cell_id: int, yield_time_ms: int = 5_000, terminate: bool = False
    ) -> ToolResult:
        invocation = self.invocation(
            {"cell_id": cell_id, "yield_time_ms": yield_time_ms, "terminate": terminate}
        )
        outcome = self.wait_tool.run(invocation, ToolContext())
        assert isinstance(outcome, ToolResult)
        if outcome.details is None:
            return outcome
        return self.record(invocation, outcome)

    def last_events(self) -> list[BaseModel]:
        return self.events[f"call_{self._calls}"]

    def finish(self) -> dict[str, ToolResult]:
        results = [m for m in self.recorded if isinstance(m, ToolResultMessage)]
        amendments = self.cells.finish(results)
        return {amendment.call_id: amendment.result for amendment in amendments}

    def saved(self) -> list[Message]:
        """The recorded messages with the response's closing records applied."""
        amendments = self.finish()
        return [
            message.model_copy(
                update={
                    "content": amendments[message.tool_call_id].content,
                    "details": amendments[message.tool_call_id].details,
                }
            )
            if isinstance(message, ToolResultMessage)
            and message.tool_call_id in amendments
            else message
            for message in self.recorded
        ]

    # Live cell state, read only to synchronize the tests with the driver.
    def cell(self, cell_id: int) -> CodeCell:
        return self.cells._cells[cell_id]

    def ended(self, cell_id: int) -> bool:
        return self.cell(cell_id)._end is not None


def _details(result: ToolResult) -> CodeModeExecutionResult:
    assert isinstance(result.details, CodeModeExecutionResult), result.content
    return result.details


def test_yield_returns_output_so_far_and_wait_returns_only_new_output() -> None:
    response = Response()
    started = time.monotonic()
    first = response.run(
        "print('a')\nawait gate(value='x')\nprint('b')\n", yield_time_ms=1_000
    )
    assert time.monotonic() - started >= 0.9
    details = _details(first)
    assert (details.cell_id, details.observation, details.status) == (1, 0, "running")
    assert details.stdout == "a\n"
    assert details.code.startswith("print('a')")
    assert not first.is_error
    assert first.content.startswith("Execution running in cell 1 after 1.")
    assert first.content.endswith(
        "Cell 1 continues. Call wait_code(cell_id=1) for more output, or "
        "wait_code(cell_id=1, terminate=true) to stop it."
    )

    response.gate.set()
    second = _details(response.wait(1, yield_time_ms=30_000))
    assert (second.observation, second.status, second.stdout, second.code) == (
        1,
        "completed",
        "b\n",
        "",
    )
    assert response.wait(1).content == "Cell 1 already returned its final result."
    assert response.finish() == {}


def test_yield_control_ends_the_observation_at_once() -> None:
    response = Response()
    started = time.monotonic()
    result = response.run(
        "print('a')\nyield_control()\nawait gate(value='x')\nprint('b')\n"
    )
    # Far less than the default yield time.
    assert time.monotonic() - started < DEFAULT_EXECUTE_YIELD_MS / 2000
    assert (_details(result).status, _details(result).stdout) == ("running", "a\n")
    response.gate.set()
    final = response.wait(1, yield_time_ms=30_000)
    assert (_details(final).status, _details(final).stdout) == ("completed", "b\n")
    assert final.content.startswith("Execution completed in cell 1 in ")


def test_events_between_observations_go_to_the_next_one() -> None:
    response = Response()
    first = response.run(
        "import asyncio\n"
        "async def tick():\n"
        "    await asyncio.sleep(0.1)\n"
        "    yield_control()\n"
        "a, _ = await asyncio.gather(gate(value='x'), tick())\n"
        "print(a)\n"
        "await echo(value='y')\n"
    )
    [running] = _details(first).calls
    assert (running.index, running.state, running.is_error) == (0, "running", False)
    response.gate.set()
    until(lambda: response.ended(1))
    final = _details(response.wait(1))
    assert [(call.index, call.state) for call in final.calls] == [(0, "ok"), (1, "ok")]
    events = response.last_events()
    kinds = [
        (type(event).__name__, event.call.index)
        for event in events
        if isinstance(event, (CodeModeCallStarted, CodeModeCallFinished))
    ]
    # The carried call is announced again, then the buffered events follow.
    assert kinds == [
        ("CodeModeCallStarted", 0),
        ("CodeModeCallFinished", 0),
        ("CodeModeCallStarted", 1),
        ("CodeModeCallFinished", 1),
    ]
    assert "".join(e.text for e in events if isinstance(e, CodeModeStdout)) == "x\n"


def test_terminate_stops_the_cell() -> None:
    response = Response()
    response.run(
        # Deleting a missing key changes nothing, so the note leaves it out.
        "import asyncio\nstore('a', 1)\nstore('b', None)\nprint('a')\n"
        "yield_control()\nawait asyncio.sleep(30)\n"
    )
    started = time.monotonic()
    result = response.wait(1, terminate=True)
    assert time.monotonic() - started < 5
    details = _details(result)
    assert details.status == "terminated"
    assert not result.is_error
    assert result.content.startswith("Execution terminated in cell 1 after ")
    # A stopped program does not commit.
    assert details.commit is None
    assert result.content.endswith(
        "Store writes discarded because the program was stopped before it ended: a."
    )
    assert response.finish() == {}


def test_printed_text_streams_while_the_program_runs() -> None:
    response = Response()
    invocation = response.invocation(
        {"code": "print('a')\nwhile True:\n    pass\n", "yield_time_ms": 30_000}
    )
    running = start_thread_future(
        lambda: response.execute.run(invocation, ToolContext()), name="test-execute"
    )
    # No call event or observation end sends the text; the waiting call does.
    until(
        lambda: any(
            isinstance(event, CodeModeStdout) and event.text == "a\n"
            for event in response.events.get(invocation.call_id, [])
        )
    )
    response.cancellation.cancel()
    with pytest.raises(AgentCancelled):
        running.result(10)
    response.finish()


def test_one_active_wait_per_cell() -> None:
    response = Response()
    response.run("import asyncio\nyield_control()\nawait asyncio.sleep(30)\n")
    waiting = start_thread_future(
        lambda: response.wait(1, yield_time_ms=1_000), name="test-wait"
    )
    until(lambda: response.cell(1)._observer is not None)
    busy = response.wait(1)
    assert busy.is_error
    assert busy.content == "Cell 1 already has an active wait_code call."
    assert _details(waiting.result(10)).status == "running"
    assert _details(response.wait(1, terminate=True)).status == "terminated"


def test_unknown_and_earlier_cell_ids() -> None:
    earlier = Response()
    earlier.run("yield_control()\nimport asyncio\nawait asyncio.sleep(30)\n")
    earlier.finish()

    later = Response(history=earlier.recorded)
    stopped = later.wait(1)
    assert stopped.is_error
    assert stopped.content == (
        "Cell 1 stopped when its response ended or its run paused. Start a new "
        "execute_code call."
    )
    missing = later.wait(9)
    assert missing.content == "Cell 9 does not exist."
    # Ids continue after the highest id in the branch.
    assert _details(later.run("1\n")).cell_id == 2


def test_lifetime_ends_the_cell() -> None:
    response = Response(
        limits=SandboxLimits(
            lifetime_seconds=0.5,
            max_tool_calls=20,
            max_output_chars=2_000,
            max_memory_bytes=32 * 1024 * 1024,
            max_cpu_seconds=2,
        )
    )
    response.run("import asyncio\nyield_control()\nawait asyncio.sleep(30)\n")
    final = response.wait(1)
    assert _details(final).status == "timed_out"
    assert "did not finish within 0.5 seconds" in (_details(final).error or "")


def test_open_cell_limit() -> None:
    response = Response()
    for _ in range(MAX_OPEN_CELLS):
        response.run("import asyncio\nyield_control()\nawait asyncio.sleep(30)\n")
    refused = response.run("1\n")
    assert refused.is_error
    assert refused.details is None
    assert "Open cells: 1, 2, 3, 4." in refused.content
    response.finish()
    # Other responses are not limited by this one's cells.
    assert _details(Response().run("1\n")).status == "completed"


def test_running_cell_limit_is_process_wide(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cells_module, "_running_cells", cells_module._RunningCells(1))
    first = Response()
    first.run("import asyncio\nyield_control()\nawait asyncio.sleep(30)\n")
    refused = Response().run("1\n")
    assert refused.is_error
    assert refused.content == BUSY_MESSAGE
    first.finish()
    # The ended cell's driver gives its place back.
    until(lambda: cells_module._running_cells.acquire("unknown"))
    cells_module._running_cells.release("unknown", 0.0)
    assert _details(Response().run("1\n")).status == "completed"


def test_a_cell_whose_driver_cannot_start_ends_and_frees_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cells_module, "_running_cells", cells_module._RunningCells(1))

    def no_thread(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("can't start new thread")

    response = Response()
    with monkeypatch.context() as patched:
        patched.setattr(cells_module, "start_thread_future", no_thread)
        failed = response.run("1\n")
    assert _details(failed).status == "failed"
    assert "can't start new thread" in (_details(failed).error or "")
    started = time.monotonic()
    assert response.finish() == {}
    assert time.monotonic() - started < 1
    # The failed cell gave its slot back.
    assert _details(Response().run("1\n")).status == "completed"


def test_commits_follow_completion_order_and_saved_records_fold_to_the_same_store() -> (
    None
):
    response = Response()
    response.run("yield_control()\nstore('k', 'a')\nstore('only_a', 1)\n")
    until(lambda: response.ended(1))
    # A completed without an observer; a later program sees its commit at once.
    assert _details(response.run("load('only_a')\n")).result == "1"
    b = _details(response.run("store('k', 'b')\n")).commit
    assert b is not None and b.writes == {"k": "b"}
    a_details = _details(response.wait(1))
    assert a_details.status == "completed"
    # A's record keeps all its writes; its ordinal places it before B's.
    a = a_details.commit
    assert a is not None and a.writes == {"k": "a", "only_a": 1}
    assert a.ordinal < b.ordinal
    assert _details(response.run("load('k')\n")).result == "'b'"

    later = Response(history=response.recorded)
    assert _details(later.run("[load('k'), load('only_a')]\n")).result == "['b', 1]"
    # Ordinals continue after the highest one in the branch.
    c = _details(later.run("store('k', 'c')\n")).commit
    assert c is not None and c.ordinal == b.ordinal + 1


def test_same_step_execute_and_wait_fold_to_the_live_store() -> None:
    response = Response()
    response.run("yield_control()\nawait gate(value='x')\nstore('k', 'a')\n")
    # One step calls execute_code and wait_code; both see the same history. The
    # calls run one after the other so that A's commit lands before B's, but the
    # model's order saves B's result first.
    wait_invocation = response.invocation({"cell_id": 1, "yield_time_ms": 30_000})
    execute_invocation = response.invocation({"code": "store('k', 'b')\n"})
    response.gate.set()
    waited = response.wait_tool.run(wait_invocation, ToolContext())
    executed = response.execute.run(execute_invocation, ToolContext())
    assert isinstance(waited, ToolResult) and isinstance(executed, ToolResult)
    assert _details(waited).status == "completed"
    response.record(execute_invocation, executed)
    response.record(wait_invocation, waited)
    assert _details(response.run("load('k')\n")).result == "'b'"

    later = Response(history=response.saved())
    assert _details(later.run("load('k')\n")).result == "'b'"


def test_a_commit_keeps_writes_that_change_the_store_at_commit_time() -> None:
    response = Response()
    response.run("store('x', 1)\n")
    # A starts with x == 1 and no y; B changes both before A ends.
    response.run(
        "yield_control()\nawait gate(value='g')\nstore('x', 1)\nstore('y', None)\n"
    )
    response.run("store('x', 2)\nstore('y', 5)\n")
    response.gate.set()
    a = _details(response.wait(2)).commit
    assert a is not None and a.writes == {"x": 1, "y": None}
    assert _details(response.run("[load('x'), load('y')]\n")).result == "[1, None]"


@pytest.mark.parametrize(
    ("limit", "reason"),
    [
        ("MAX_STORE_BYTES", "the store would hold"),
        ("MAX_COMMITTED_BYTES", "this chat would save"),
    ],
)
def test_concurrent_commits_together_stay_within_the_store_limits(
    monkeypatch: pytest.MonkeyPatch, limit: str, reason: str
) -> None:
    monkeypatch.setattr(store_module, limit, 100)
    response = Response()
    # A and B start on the same empty store; each fits, both do not.
    response.run("yield_control()\nawait gate(value='g')\nstore('a', 'x' * 60)\n")
    b = _details(response.run("store('b', 'y' * 60)\n")).commit
    assert b is not None
    response.gate.set()
    waited = response.wait(1)
    assert _details(waited).status == "completed"
    assert _details(waited).commit is None
    assert (
        f"Store writes discarded because other programs committed first, so {reason}"
        in waited.content
    )
    assert waited.content.rstrip().endswith(": a.")
    assert _details(response.run("[load('a'), load('b')]\n")).result == (
        f"[None, '{'y' * 60}']"
    )


def test_a_write_equal_to_the_start_store_reports_its_discard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store_module, "MAX_COMMITTED_BYTES", 70)
    response = Response()
    response.run("store('k', 'v')\n")
    # A writes the value it started with; B then replaces it and nears the limit.
    response.run("yield_control()\nawait gate(value='g')\nstore('k', 'v')\n")
    assert _details(response.run("store('k', 'y' * 60)\n")).commit is not None
    response.gate.set()
    waited = response.wait(2)
    assert _details(waited).commit is None
    assert (
        "Store writes discarded because other programs committed first, so this "
        "chat would save"
    ) in waited.content
    assert waited.content.rstrip().endswith(": k.")
    assert _details(response.run("load('k')\n")).result == repr("y" * 60)


def test_closing_record_lists_what_ran_after_the_last_observation() -> None:
    response = Response()
    first = response.run(
        "import asyncio\nyield_control()\nawait echo(value='x')\nprint('after')\n"
        "store('done', True)\n"
    )
    until(lambda: response.ended(1))
    amendments = response.finish()
    amended = amendments["call_1"]
    details = _details(amended)
    assert details.status == "running"
    closing = details.closing
    assert closing is not None
    assert (closing.reason, closing.status, closing.stdout) == (
        "response_ended",
        "completed",
        "after\n",
    )
    assert [(call.function_name, call.state) for call in closing.calls] == [
        ("echo", "ok")
    ]
    assert closing.commit is not None and closing.commit.writes == {"done": True}
    assert amended.content.startswith(first.content)
    assert amended.content.endswith(
        "Cell 1 completed after this output, before the response ended.\n\n"
        "Output:\nafter\n\nStored: done."
    )
    # The closing record commits for later turns.
    later = Response(
        history=[
            ToolResultMessage(
                tool_call_id="call_1",
                tool_name="execute_code",
                content=amended.content,
                details=amended.details,
            )
        ]
    )
    assert _details(later.run("load('done')\n")).result == "True"


def test_a_failed_program_lists_the_calls_of_every_observation() -> None:
    response = Response()
    response.run("await echo(value='x')\nyield_control()\nraise ValueError('boom')\n")
    failed = response.wait(1)
    assert _details(failed).status == "failed"
    assert _details(failed).calls == []
    assert "Tool calls:\n[0] echo: ok\n" in failed.content


def test_closing_record_lists_earlier_calls_of_a_stopped_program() -> None:
    response = Response()
    response.run("await echo(value='x')\nyield_control()\nwhile True:\n    pass\n")
    amended = response.finish()["call_1"]
    assert amended.content.endswith(
        "Cell 1 stopped when the response ended.\n\nTool calls:\n[0] echo: ok\n"
        "All of these calls may have had effects, also unfinished calls. Check "
        "before you retry."
    )


def test_closing_record_reports_output_result_and_store_without_calls() -> None:
    response = Response()
    response.run("yield_control()\nprint('late')\nstore('k', 1)\n{'total': 3}\n")
    until(lambda: response.ended(1))
    amended = response.finish()["call_1"]
    closing = _details(amended).closing
    assert closing is not None
    assert closing.result == "{'total': 3}"
    assert amended.content.endswith(
        "Cell 1 completed after this output, before the response ended.\n\n"
        "Output:\nlate\n\nResult:\n{'total': 3}\n\nStored: k."
    )


def test_output_after_a_yield_goes_to_the_next_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printed = threading.Event()

    class LateWake(threading.Condition):
        """The observer wakes only after the program printed past its yield."""

        def wait(self, timeout: float | None = None) -> bool:
            woken = super().wait(timeout)
            if not printed.is_set():
                self.release()
                try:
                    printed.wait(10)
                finally:
                    self.acquire()
            return woken

    init = CodeCell.__init__
    print_ = CodeCell._print

    def late_wake_init(cell: CodeCell, *args: Any, **kwargs: Any) -> None:
        init(cell, *args, **kwargs)
        cell._changed = LateWake(cell._lock)

    def signalled_print(cell: CodeCell, text: str) -> None:
        print_(cell, text)
        printed.set()

    monkeypatch.setattr(CodeCell, "__init__", late_wake_init)
    monkeypatch.setattr(CodeCell, "_print", signalled_print)
    response = Response()
    observed = response.run("yield_control()\nprint('late')\n")
    assert _details(observed).stdout == ""
    until(lambda: response.ended(1))
    closing = _details(response.finish()["call_1"]).closing
    assert closing is not None and closing.stdout == "late\n"


def test_stop_kills_a_busy_loop_without_an_observer() -> None:
    response = Response()
    response.run("yield_control()\nwhile True:\n    pass\n")
    started = time.monotonic()
    response.cancellation.cancel()
    amended = response.finish()["call_1"]
    assert time.monotonic() - started < 15
    closing = _details(amended).closing
    assert closing is not None
    assert closing.status == "cancelled"


def test_stop_with_a_slow_driver_closes_the_cell_as_cancelled_within_the_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cells_module, "STOP_GRACE_SECONDS", 0.5)
    release = threading.Event()

    def ignores_stop(
        _code: str, *, on_yield: Callable[[], None], **_kwargs: object
    ) -> SandboxResult:
        on_yield()
        release.wait(10)
        return SandboxResult(status="cancelled")

    monkeypatch.setattr(cells_module, "execute_program", ignores_stop)
    response = Response()
    response.run("1\n")
    response.cancellation.cancel()
    started = time.monotonic()
    amended = response.finish()["call_1"]
    # The grace counts from Stop; the driver itself would return only after 10 s.
    assert time.monotonic() - started < 5
    release.set()
    closing = _details(amended).closing
    assert closing is not None
    assert closing.status == "cancelled"


def test_a_call_waiting_for_a_sequential_tool_stops_with_its_cell() -> None:
    response = Response()
    response.run(
        "import asyncio\nyield_control()\n"
        "await asyncio.gather(seq(value='a'), seq(value='b'))\n"
    )
    until(lambda: len(response.cell(1)._calls) == 2)
    assert _details(response.wait(1, terminate=True)).status == "terminated"
    # The call that holds the lock ignores cancellation; the waiting one returns.
    until(lambda: len(response.cell(1).running_calls()) == 1, timeout=3)
    response.gate.set()
    until(lambda: not response.cell(1).running_calls())


def test_citations_do_not_collide_across_observations() -> None:
    response = Response()
    context = ToolContext(next_citation_num=1)
    first = response.run(
        "await web_search(queries=['a'])\nyield_control()\nimport asyncio\n"
        "await asyncio.sleep(0.2)\nawait web_search(queries=['b'])\n",
        context=context,
    )
    second = _details(response.wait(1))

    def searches(details: CodeModeExecutionResult) -> list[SearchDocsResponse]:
        return [
            call.details
            for call in details.calls
            if isinstance(call.details, SearchDocsResponse)
        ]

    [first_search] = searches(_details(first))
    [second_search] = searches(second)
    assert sorted(first_search.citation_mapping) == [1, 2]
    assert sorted(second_search.citation_mapping) == [3, 4]
    assert {doc.document_id for doc in second_search.search_docs} == {"b-0", "b-1"}


def test_restored_running_observation_is_amended_as_interrupted() -> None:
    saved = CodeModeExecutionResult(
        cell_id=3,
        observation=0,
        code="x",
        status="running",
        calls=[
            CodeModeCall(
                index=0,
                id="old:0",
                tool_name="acme",
                function_name="acme_ok",
                arguments={},
                state="ok",
            ),
            CodeModeCall(
                index=1,
                id="old:1",
                tool_name="acme",
                function_name="acme_running",
                arguments={},
                state="running",
            ),
        ],
    )
    history: list[Message] = [
        ToolResultMessage(
            tool_call_id="old",
            tool_name="execute_code",
            content="Execution running",
            details=saved,
        )
    ]
    response = Response(history=history)
    assert response.wait(3).content == (
        "Cell 3 stopped when its response ended or its run paused. Start a new "
        "execute_code call."
    )
    amended = response.finish()["old"]
    closing = _details(amended).closing
    assert closing is not None
    assert closing.reason == "interrupted"
    # The calls that the saved observations hold may have had effects.
    assert amended.content.endswith(
        "Cell 3 was interrupted when the server stopped. Calls after this output are "
        "not known; they may have run.\n\nTool calls:\n[0] acme_ok: ok\n"
        "[1] acme_running: unfinished\nAll of these calls may have had effects, "
        "also unfinished calls. Check before you retry."
    )


_CAPACITY_SAMPLES: tuple[tuple[str, dict[str, str]], ...] = (
    ("onyx_code_mode_cells_running", {}),
    ("onyx_code_mode_sandbox_workers_busy", {}),
    ("onyx_code_mode_tool_call_threads_in_use", {}),
    ("onyx_code_mode_programs_waiting_for_worker", {}),
    ("onyx_code_mode_program_duration_seconds_count", {}),
    ("onyx_code_mode_program_start_duration_seconds_count", {}),
)


def _samples() -> dict[str, float]:
    return {
        name: REGISTRY.get_sample_value(name, labels) or 0.0
        for name, labels in _CAPACITY_SAMPLES
    }


_IN_USE_GAUGES = (
    "onyx_code_mode_cells_running",
    "onyx_code_mode_sandbox_workers_busy",
    "onyx_code_mode_tool_call_threads_in_use",
)


def test_capacity_metrics_follow_one_program() -> None:
    # Cells from earlier tests may still be finishing.
    until(lambda: all(_samples()[name] == 0 for name in _IN_USE_GAUGES))
    before = _samples()

    def delta(name: str) -> float:
        return _samples()[name] - before[name]

    response = Response()
    running = response.run(
        "await gate(value='x')\nprint('done')\n", yield_time_ms=1_000
    )
    assert _details(running).status == "running"
    # A lone waiting program keeps its worker; its call holds a thread.
    assert delta("onyx_code_mode_cells_running") == 1
    assert delta("onyx_code_mode_sandbox_workers_busy") == 1
    assert delta("onyx_code_mode_tool_call_threads_in_use") == 1

    response.gate.set()
    assert _details(response.wait(1, yield_time_ms=30_000)).status == "completed"
    until(lambda: delta("onyx_code_mode_cells_running") == 0)
    assert delta("onyx_code_mode_program_duration_seconds_count") == 1
    assert delta("onyx_code_mode_program_start_duration_seconds_count") == 1
    assert delta("onyx_code_mode_sandbox_workers_busy") == 0
    assert delta("onyx_code_mode_tool_call_threads_in_use") == 0
    assert delta("onyx_code_mode_programs_waiting_for_worker") == 0


def test_a_crash_keeps_only_commits_whose_earlier_commits_are_saved() -> None:
    response = Response()
    # Cell 1 commits after its first observation; no saved record reports it yet.
    response.run("yield_control()\nstore('a', 1)\n")
    until(lambda: response.ended(1))
    # Cell 2 is stuck on a call; cell 3 does not wait for it.
    stuck = response.run("await gate(value='x')\n", yield_time_ms=100)
    assert _details(stuck).status == "running"
    started = time.monotonic()
    dependent = _details(response.run("store('b', load('a') + 1)\n"))
    assert time.monotonic() - started < 5
    assert dependent.status == "completed" and dependent.commit is not None

    # The server stops: only the recorded results are saved. Cell 3's commit
    # depends on cell 1's, which was never saved.
    crashed = Response(history=response.recorded)
    assert _details(crashed.run("[load('a'), load('b')]\n")).result == "[None, None]"
    # Commits after the restore still apply.
    crashed.run("store('c', 3)\n")
    restored = Response(history=crashed.recorded)
    assert _details(restored.run("[load('b'), load('c')]\n")).result == "[None, 3]"

    # Without a crash, the closing records save every commit.
    response.gate.set()
    finished = Response(history=response.saved())
    assert _details(finished.run("[load('a'), load('b')]\n")).result == "[1, 2]"


def test_the_first_program_after_a_crash_reports_the_dropped_writes_once() -> None:
    response = Response()
    # Cell 1 commits after its first observation; no saved record reports it.
    response.run("yield_control()\nstore('a', 1)\n")
    until(lambda: response.ended(1))
    stuck = response.run("await gate(value='x')\n", yield_time_ms=100)
    assert _details(stuck).status == "running"
    # Cell 3's commit follows cell 1's, so the crash drops it.
    assert _details(response.run("store('b', load('a') + 1)\n")).commit is not None
    response.gate.set()

    # The server stops: only the recorded results are saved.
    crashed = Response(history=response.recorded)
    note = (
        "Store writes of an earlier program were discarded because the program "
        "before it did not finish saving its own: b."
    )
    first = crashed.run("1\n")
    assert note in first.content
    lost = _details(first).lost_store_writes
    assert lost is not None and lost.keys == ("b",)
    # Later programs, in this response and after a reload, do not repeat it.
    assert note not in crashed.run("2\n").content
    reloaded = Response(history=crashed.recorded)
    assert note not in reloaded.run("3\n").content
    # Cells that start before either one's result is saved report it once too.
    parallel = Response(history=response.recorded)
    store = parallel.cells._store
    snapshot = store.snapshot(parallel.recorded)
    assert snapshot.dropped
    store.reported(snapshot)
    assert not store.snapshot(parallel.recorded).dropped


def test_a_cell_rejected_as_busy_leaves_the_dropped_writes_note_to_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Response()
    response.run("yield_control()\nstore('a', 1)\n")
    until(lambda: response.ended(1))
    stuck = response.run("await gate(value='x')\n", yield_time_ms=100)
    assert _details(stuck).status == "running"
    assert _details(response.run("store('b', load('a') + 1)\n")).commit is not None
    response.gate.set()

    crashed = Response(history=response.recorded)
    with monkeypatch.context() as patched:
        # Every running-cell slot is taken.
        patched.setattr(
            cells_module._running_cells, "acquire", lambda _tenant_id: False
        )
        refused = crashed.run("1\n")
    assert refused.content == BUSY_MESSAGE
    accepted = crashed.run("2\n")
    lost = _details(accepted).lost_store_writes
    assert lost is not None and lost.keys == ("b",)


def _tenant_sample(name: str, tenant_id: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, {"tenant_id": tenant_id, **labels}) or 0.0


def test_tenant_counters_follow_one_program_and_one_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = "tenant_cell_metrics"
    names = (
        ("onyx_code_mode_programs_total", {"status": "completed"}),
        ("onyx_code_mode_cell_seconds_total", {}),
        ("onyx_code_mode_cell_busy_rejections_total", {}),
        ("onyx_code_mode_sandbox_worker_seconds_total", {}),
    )

    def samples() -> list[float]:
        return [_tenant_sample(name, tenant_id, **labels) for name, labels in names]

    monkeypatch.setattr(cells_module, "_running_cells", cells_module._RunningCells(1))
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        before = samples()
        response = Response()
        running = response.run("await gate(value='x')\n", yield_time_ms=300)
        assert _details(running).status == "running"
        refused = Response().run("1\n")
        response.gate.set()
        assert _details(response.wait(1, yield_time_ms=30_000)).status == "completed"
        until(lambda: samples()[1] > before[1])
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    assert refused.content == BUSY_MESSAGE
    programs, cell_seconds, rejections, worker_seconds = (
        after - start for after, start in zip(samples(), before, strict=True)
    )
    assert (programs, rejections) == (1, 1)
    # The cell held its slot from its start to its program's end.
    assert 0.3 <= cell_seconds < 10, cell_seconds
    assert 0 < worker_seconds <= cell_seconds


def test_a_cell_that_ends_after_its_closing_record_commits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cells_module, "STOP_GRACE_SECONDS", 0.1)
    release = threading.Event()
    execute = cells_module.execute_program

    def late_end(code: str, **kwargs: Any) -> SandboxResult:
        """Ignores the stop, then completes after its cell closed."""
        if code != "late":
            return execute(code, **kwargs)
        kwargs["plain_functions"]["store"]("a", 1)
        assert release.wait(10)
        return SandboxResult(status="completed", commits_store=True)

    monkeypatch.setattr(cells_module, "execute_program", late_end)
    response = Response()
    assert _details(response.run("late", yield_time_ms=100)).status == "running"
    # The run pauses; the closing record stops waiting for cell 1 and says it
    # stopped.
    results = [m for m in response.recorded if isinstance(m, ToolResultMessage)]
    closing = {
        amendment.call_id: amendment.result
        for amendment in response.cells.suspend(results)
    }
    assert closing["call_1"].content.endswith("Cell 1 stopped when the run paused.")
    release.set()
    until(lambda: response.ended(1))
    # A later cell of the response does not build on a commit that no saved
    # record reports.
    assert _details(response.run("store('b', 2)\n")).commit is not None
    saved = [
        message.model_copy(
            update={
                "content": closing[message.tool_call_id].content,
                "details": closing[message.tool_call_id].details,
            }
        )
        if isinstance(message, ToolResultMessage) and message.tool_call_id in closing
        else message
        for message in response.recorded
    ]
    restored = Response(history=saved)
    assert _details(restored.run("[load('a'), load('b')]\n")).result == "[None, 2]"
