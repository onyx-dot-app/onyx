"""Cell lifecycle: yields, waits, termination, limits, store commits and closing records."""

import threading
import time
from collections.abc import Callable, Sequence

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
    CodeModeCallFinished,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStdout,
    SandboxLimits,
    SandboxResult,
)
from onyx.tools.tool_implementations.code_mode.sandbox import BUSY_MESSAGE
from onyx.utils.threadpool_concurrency import start_thread_future
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
    waiting = threading.Thread(target=lambda: response.wait(1, yield_time_ms=1_000))
    waiting.start()
    until(lambda: response.cell(1)._observer is not None)
    busy = response.wait(1)
    assert busy.is_error
    assert busy.content == "Cell 1 already has an active wait_code call."
    waiting.join()
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
    until(lambda: cells_module._running_cells.acquire())
    cells_module._running_cells.release()
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


def test_parallel_execute_and_wait_fold_to_the_live_store() -> None:
    response = Response()
    response.run("yield_control()\nawait gate(value='x')\nstore('k', 'a')\n")
    # One step calls execute_code and wait_code; both see the same history. The
    # wait reports A's commit, which completes before B's, but the model's order
    # saves B's result first.
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
    assert f"Store writes discarded because {reason}" in waited.content
    assert waited.content.rstrip().endswith(": a.")
    assert _details(response.run("[load('a'), load('b')]\n")).result == (
        f"[None, '{'y' * 60}']"
    )


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
        "Cell 1 completed after this output, before the response ended. Calls after "
        "this output: [0] echo: ok. Completed calls may have had effects. "
        "Stored: done."
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
        "Cell 1 stopped when the response ended. Calls before this output: "
        "[0] echo: ok. It made no calls after this output."
    )


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
        cell_id=3, observation=0, code="x", status="running"
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
    assert amended.content.endswith(
        "Cell 3 was interrupted when the server stopped. Calls after this output are "
        "not known; they may have run."
    )


_CAPACITY_SAMPLES: tuple[tuple[str, dict[str, str]], ...] = (
    ("onyx_code_mode_cells_running", {}),
    ("onyx_code_mode_sandbox_workers_busy", {}),
    ("onyx_code_mode_tool_call_threads_in_use", {}),
    ("onyx_code_mode_programs_waiting_for_worker", {}),
    ("onyx_code_mode_programs_total", {"status": "completed"}),
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
    assert delta("onyx_code_mode_programs_total") == 1
    assert delta("onyx_code_mode_program_duration_seconds_count") == 1
    assert delta("onyx_code_mode_program_start_duration_seconds_count") == 1
    assert delta("onyx_code_mode_sandbox_workers_busy") == 0
    assert delta("onyx_code_mode_tool_call_threads_in_use") == 0
    assert delta("onyx_code_mode_programs_waiting_for_worker") == 0
