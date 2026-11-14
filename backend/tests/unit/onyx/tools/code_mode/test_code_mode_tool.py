import json
import re
import threading
import time

import pytest
from pydantic import BaseModel, JsonValue

from onyx.agents.compaction import count_tokens
from onyx.agents.tools import (
    ChildRunWait,
    ToolExecutionMode,
    ToolInvocation,
    ToolOutcome,
    ToolProgress,
)
from onyx.chat.tool_results import ResultSources, tool_result_sources
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    current_cancellation,
)
from onyx.llm.models import ToolResult
from onyx.tools.constants import PYTHON_TOOL_NAME
from onyx.tools.interface import CITATIONS_PER_TOOL_CALL
from onyx.tools.models import (
    ChatFile,
    CodeModeExposure,
    CustomToolCallSummary,
    ToolContext,
    ToolExecutionError,
)
from onyx.tools.tool_implementations.code_mode import cells
from onyx.tools.tool_implementations.code_mode import (
    code_mode_tool as code_mode_tool_module,
)
from onyx.tools.tool_implementations.code_mode.cells import (
    CELL_SPAN_NAME,
    MAX_SAVED_CALL_CHARS,
    CodeCells,
    durable_details,
)
from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
    CodeModeTool,
    WaitCodeTool,
)
from onyx.tools.tool_implementations.code_mode.models import (
    UNFINISHED_CALL_MESSAGE,
    CodeModeCallFinished,
    CodeModeCallProgress,
    CodeModeCallStarted,
    CodeModeExecutionResult,
    CodeModeStdout,
    SandboxLimits,
    json_text,
)
from onyx.tools.tool_implementations.search.models import SearchPlanningResult
from onyx.tracing.framework import set_trace_processors
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.span_data import FunctionSpanData
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.unit.onyx.tools.code_mode.fakes import (
    LIMITS,
    FakeMCPTool,
    FakeTool,
    FakeWebSearchTool,
    echo,
    search,
    search_result,
    until,
)
from tests.unit.onyx.tracing.capture import CaptureProcessor


class Progress(BaseModel):
    step: str


def _sources(details: CodeModeExecutionResult) -> ResultSources:
    sources = tool_result_sources(details)
    assert sources is not None
    return sources


def _web_search(invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
    invocation.update(ToolProgress(details=Progress(step="searching")))
    time.sleep(0.3)
    return search(invocation, context)


def _broken(_invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
    raise ValueError("backend unavailable")


def _make_tool(*tools: FakeTool | FakeWebSearchTool | FakeMCPTool) -> CodeModeTool:
    return CodeModeTool(
        [FakeWebSearchTool(_web_search), FakeTool("echo", echo), *tools],
        cells=CodeCells(),
        limits=LIMITS,
    )


class Invocation:
    def __init__(self, code: str) -> None:
        self.events: list[BaseModel] = []
        self.cancellation = CancellationSignal()
        self.invocation = ToolInvocation(
            call_id="call_1",
            arguments={"code": code},
            cancellation=self.cancellation,
            update=self._update,
        )

    def _update(self, progress: ToolProgress) -> None:
        assert progress.details is not None
        self.events.append(progress.details)


def _run(
    tool: CodeModeTool,
    code: str,
    context: ToolContext | None = None,
) -> tuple[ToolResult, CodeModeExecutionResult, list[BaseModel]]:
    invocation = Invocation(code)
    outcome = tool.run(invocation.invocation, context or ToolContext())
    assert isinstance(outcome, ToolResult)
    assert isinstance(outcome.details, CodeModeExecutionResult)
    return outcome, outcome.details, invocation.events


def test_parallel_searches_get_separate_citation_blocks_and_merge() -> None:
    tool = _make_tool()
    result, details, events = _run(
        tool,
        "import asyncio\n"
        "a, b = await asyncio.gather(web_search(queries=['x']), "
        "web_search(queries=['y']))\n"
        "for doc in a['results'] + b['results']:\n"
        "    print(doc['document'], doc['title'])\n",
        ToolContext(next_citation_num=5),
    )
    assert not result.is_error
    assert details.status == "completed"
    numbers = sorted(_sources(details).citations)
    first_block = [5, 6]
    second_block = [5 + CITATIONS_PER_TOOL_CALL, 6 + CITATIONS_PER_TOOL_CALL]
    assert numbers == first_block + second_block
    assert {doc.document_id for doc in _sources(details).documents} == {
        "x-0",
        "x-1",
        "y-0",
        "y-1",
    }
    assert result.content.startswith("Execution completed in ")
    assert "with 2 tool calls." in result.content
    for number in numbers:
        assert f"{number} Title" in result.content
    assert [call.index for call in details.calls] == [0, 1]
    assert all(isinstance(call.details, SearchDocsResponse) for call in details.calls)

    # Nothing is in flight now: the next call starts after the highest used number.
    _, later, _ = _run(
        tool, "await web_search(queries=['z'])\n", ToolContext(next_citation_num=5)
    )
    assert sorted(_sources(later).citations) == [
        7 + CITATIONS_PER_TOOL_CALL,
        8 + CITATIONS_PER_TOOL_CALL,
    ]
    # Each call streams its start, its progress and its saved record.
    assert sorted(
        e.call.index for e in events if isinstance(e, CodeModeCallStarted)
    ) == [0, 1]
    assert sorted(e.index for e in events if isinstance(e, CodeModeCallProgress)) == [
        0,
        1,
    ]
    finished = [e.call for e in events if isinstance(e, CodeModeCallFinished)]
    assert sorted(finished, key=lambda call: call.index) == details.calls


def test_progress_events_follow_call_order() -> None:
    _, details, events = _run(
        _make_tool(),
        "print('start')\nr = await web_search(queries=['q'])\nprint('end')\n",
    )
    kinds = [
        (
            type(event).__name__,
            event.index
            if isinstance(event, CodeModeCallProgress)
            else event.call.index,
        )
        for event in events
        if isinstance(
            event, (CodeModeCallStarted, CodeModeCallProgress, CodeModeCallFinished)
        )
    ]
    assert kinds == [
        ("CodeModeCallStarted", 0),
        ("CodeModeCallProgress", 0),
        ("CodeModeCallFinished", 0),
    ]
    started = next(e for e in events if isinstance(e, CodeModeCallStarted))
    assert started.call.tool_name == "web_search"
    assert started.call.arguments == {"queries": ["q"]}
    progress = next(e for e in events if isinstance(e, CodeModeCallProgress))
    assert progress.details == Progress(step="searching")
    finished = next(e for e in events if isinstance(e, CodeModeCallFinished))
    assert finished.call == details.calls[0]
    stdout = "".join(e.text for e in events if isinstance(e, CodeModeStdout))
    assert stdout == "start\nend\n"
    assert details.stdout == "start\nend\n"


def test_untyped_tool_returns_parsed_json_and_records_the_call() -> None:
    result, details, _ = _run(_make_tool(), "(await echo(value='hi'))['echo']\n")
    assert details.result == "'hi'"
    assert "Result:\n'hi'" in result.content
    [call] = details.calls
    assert call.tool_name == "echo"
    assert call.function_name == "echo"
    assert call.content == '{"echo": "hi"}'
    assert call.details is None


def test_tool_errors_are_raised_in_the_program() -> None:
    tool = _make_tool(FakeTool("broken", _broken))
    result, details, _ = _run(
        tool,
        "try:\n"
        "    await broken(value='x')\n"
        "except Exception as error:\n"
        "    print('caught', error)\n",
    )
    assert details.status == "completed"
    assert "caught Tool failed with error: backend unavailable" in details.stdout
    assert details.calls[0].is_error
    assert not result.is_error


def test_failed_program_is_an_error_result_with_traceback() -> None:
    result, details, _ = _run(_make_tool(), "print('partial')\n1 / 0\n")
    assert result.is_error
    assert details.status == "failed"
    assert result.content.startswith("Execution failed in ")
    assert "Output:\npartial" in result.content
    assert "line 2" in result.content
    assert "ZeroDivisionError" in result.content


def test_a_tool_that_waits_for_child_runs_fails_inside_the_program() -> None:
    def wait_for_children(
        _invocation: ToolInvocation, _context: ToolContext
    ) -> ToolOutcome:
        return ChildRunWait(run_ids=["run"])

    tool = CodeModeTool(
        [FakeTool("waits", wait_for_children)], cells=CodeCells(), limits=LIMITS
    )
    _, details, _ = _run(
        tool,
        "try:\n    await waits(value='x')\nexcept Exception as e:\n    print(e)\n",
    )
    assert "returned no result inside a program" in details.stdout
    # The call ended with the exception, before the program did.
    [call] = details.calls
    assert call.state == "error"
    assert isinstance(call.details, ToolExecutionError)
    assert "returned no result inside a program" in call.details.message


@pytest.mark.parametrize(
    ("mode", "overlaps"),
    [(ToolExecutionMode.SEQUENTIAL, False), (ToolExecutionMode.PARALLEL, True)],
)
def test_only_sequential_tools_do_not_overlap(
    mode: ToolExecutionMode, overlaps: bool
) -> None:
    active = 0
    overlap = False
    lock = threading.Lock()

    def remember(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        nonlocal active, overlap
        with lock:
            active += 1
            overlap = overlap or active > 1
        time.sleep(0.1)
        with lock:
            active -= 1
        return ToolResult(content=str(invocation.arguments["value"]))

    tool = CodeModeTool(
        [FakeTool("add_memory", remember, execution_mode=mode)],
        cells=CodeCells(),
        limits=LIMITS,
    )
    _, details, _ = _run(
        tool,
        "import asyncio\n"
        "await asyncio.gather(*[add_memory(value=str(i)) for i in range(3)])\n",
    )
    assert details.status == "completed"
    assert overlap is overlaps


def test_cancellation_stops_calls_and_raises() -> None:
    started = threading.Semaphore(0)
    stopped = threading.Semaphore(0)

    def slow(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        started.release()
        try:
            for _ in range(500):
                invocation.cancellation.check()
                time.sleep(0.02)
            return ToolResult(content="done")
        finally:
            stopped.release()

    tool = CodeModeTool([FakeTool("slow", slow)], cells=CodeCells(), limits=LIMITS)
    invocation = Invocation(
        "import asyncio\nawait asyncio.gather(slow(value='a'), slow(value='b'))\n"
    )

    def cancel_once_both_run() -> None:
        assert started.acquire(timeout=10) and started.acquire(timeout=10)
        invocation.cancellation.cancel()

    canceller = start_thread_future(cancel_once_both_run, name="test-cancel")
    with pytest.raises(AgentCancelled):
        tool.run(invocation.invocation, ToolContext())
    canceller.result(10)
    # Both calls observe the cancellation instead of running for 10 seconds.
    assert stopped.acquire(timeout=5) and stopped.acquire(timeout=5)

    def finished_calls() -> list[CodeModeCallFinished]:
        return [e for e in invocation.events if isinstance(e, CodeModeCallFinished)]

    # The cell records the calls when its program ends, after run() raised.
    until(lambda: len(finished_calls()) == 2)
    finished = finished_calls()
    assert {event.call.state for event in finished} == {"unfinished"}
    assert {event.call.content for event in finished} == {UNFINISHED_CALL_MESSAGE}
    # Clients show an unfinished call as failed.
    assert {
        event.call.details.message
        for event in finished
        if isinstance(event.call.details, ToolExecutionError)
    } == {UNFINISHED_CALL_MESSAGE}
    # Nothing is sent once the execution has closed.
    assert isinstance(invocation.events[-1], CodeModeCallFinished)


def test_output_is_cut_to_the_token_budget_in_the_middle() -> None:
    invocation = Invocation("for i in range(500):\n    print('line', i)\n")
    invocation.invocation.arguments["max_output_tokens"] = 200
    result = _make_tool().run(invocation.invocation, ToolContext())
    assert isinstance(result, ToolResult)
    content = result.content
    assert content.startswith("Warning: truncated output (original token count: ")
    assert "\nTotal output lines: " in content
    assert "tokens truncated…" in content
    assert "Execution completed" in content
    assert content.rstrip().endswith("line 499")
    assert count_tokens(content) < 260


def test_a_requested_budget_over_the_maximum_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(code_mode_tool_module, "MAX_OUTPUT_TOKENS", 200)
    invocation = Invocation("for i in range(500):\n    print('line', i)\n")
    invocation.invocation.arguments["max_output_tokens"] = 1_000_000
    result = _make_tool().run(invocation.invocation, ToolContext())
    assert isinstance(result, ToolResult)
    assert result.content.startswith("Warning: truncated output")
    assert count_tokens(result.content) < 260


def test_output_and_result_over_the_budget_are_cut_once_with_the_true_count() -> None:
    invocation = Invocation(
        "for i in range(150):\n    print('line', i)\n' '.join(['word'] * 300)\n"
    )
    invocation.invocation.arguments["max_output_tokens"] = 200
    result = _make_tool().run(invocation.invocation, ToolContext())
    assert isinstance(result, ToolResult)
    content = result.content
    assert content.count("Warning: truncated output") == 1
    match = re.search(r"original token count: (\d+)", content)
    assert match is not None
    # Both parts are within the character cap and over the token budget.
    printed = "".join(f"line {i}\n" for i in range(150))
    result_text = repr(" ".join(["word"] * 300))
    assert int(match.group(1)) >= count_tokens(printed) + count_tokens(result_text)
    assert count_tokens(content) < 260


def test_cell_and_nested_tool_spans_carry_code_mode_attributes() -> None:
    capture = CaptureProcessor()
    set_trace_processors([capture])
    try:
        with trace("code_mode"):
            _run(
                _make_tool(),
                "import asyncio\n"
                "await asyncio.gather(echo(value='a'), echo(value='b'))\n",
            )
            until(
                lambda: any(
                    s.span_data.name == CELL_SPAN_NAME for s in capture.ended_spans
                )
            )
    finally:
        set_trace_processors([])
    spans = [
        s for s in capture.ended_spans if isinstance(s.span_data, FunctionSpanData)
    ]
    (cell,) = [s for s in spans if s.span_data.name == CELL_SPAN_NAME]
    metadata = dict(cell.span_data.metadata or {})
    assert metadata.pop("code_mode.duration_seconds") > 0
    assert metadata == {
        "code_mode.cell_id": 1,
        "code_mode.status": "completed",
        "code_mode.tool_call_count": 2,
        "code_mode.tool_names": ["echo"],
    }
    nested = sorted(
        (s for s in spans if s.span_data.name == "echo"),
        key=lambda s: (s.span_data.metadata or {})["code_mode.index"],
    )
    assert [s.parent_id for s in nested] == [cell.span_id, cell.span_id]
    assert [s.span_data.metadata for s in nested] == [
        {
            "code_mode.call_id": "call_1",
            "code_mode.cell_id": 1,
            "code_mode.index": index,
            "code_mode.function_name": "echo",
        }
        for index in (0, 1)
    ]


def test_description_lists_stubs() -> None:
    first = _make_tool().tool_definition()
    assert first.name == "execute_code"
    assert first.parameters["required"] == ["code"]
    assert "asyncio.gather" in first.description
    assert "[n]" in first.description


def test_parameters_come_from_arguments() -> None:
    max_output_tokens: JsonValue = {
        "type": "integer",
        "default": 10000,
        "description": "Token budget for the output this call returns; longer "
        "output is cut in the middle. Defaults to 10000 tokens, at most 40000.",
    }
    assert _make_tool().tool_definition().parameters == {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The Python program to run."},
            "yield_time_ms": {
                "type": "integer",
                "default": 30000,
                "description": "How long to wait for the program before returning "
                "its output so far while it keeps running. Defaults to 30000 ms, at "
                "most 120000 ms.",
            },
            "max_output_tokens": max_output_tokens,
        },
        "required": ["code"],
    }
    assert WaitCodeTool(CodeCells()).tool_definition().parameters == {
        "type": "object",
        "properties": {
            "cell_id": {
                "type": "integer",
                "description": "Identifier of the running cell.",
            },
            "yield_time_ms": {
                "type": "integer",
                "default": 15000,
                "description": "How long to wait for more output before returning. "
                "Defaults to 15000 ms, at most 300000 ms.",
            },
            "max_output_tokens": max_output_tokens,
            "terminate": {
                "type": "boolean",
                "default": False,
                "description": "True stops the running cell; false or omitted waits "
                "for output.",
            },
        },
        "required": ["cell_id"],
    }


def test_mcp_like_stub_runs_and_type_checks_its_arguments() -> None:
    def list_issues(_invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        return ToolResult(content='{"issues": [{"number": 1}]}')

    tool = CodeModeTool(
        [
            FakeTool(
                "github-list_issues",
                list_issues,
                description='List issues. Matches \\d+ and """quoted""" text.',
                parameters={
                    "type": "object",
                    "properties": {
                        "repo-name": {"type": "string"},
                        "state": {"enum": ["open", "closed"]},
                        "class": {"type": "boolean"},
                    },
                    "required": ["repo-name"],
                },
            )
        ],
        cells=CodeCells(),
        limits=LIMITS,
    )
    _, details, _ = _run(
        tool,
        "r = await github_list_issues(repo_name='onyx', state='open', class_=True)\n"
        "r['issues'][0]['number']\n",
    )
    assert details.status == "completed", details.error
    assert details.result == "1"

    _, rejected, _ = _run(
        tool, "await github_list_issues(repo_name='onyx', state='x')\n"
    )
    assert rejected.status == "failed"
    assert rejected.error is not None
    assert "did not run" in rejected.error


def _list_tickets(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
    time.sleep(0.1)
    service = invocation.arguments.get("service")
    return ToolResult(
        content=json.dumps(
            {"tool_result": {"tickets": [{"id": 1, "service": service}]}}
        )
    )


_TICKET_PARAMETERS: dict[str, JsonValue] = {
    "type": "object",
    "properties": {"service": {"type": "string"}},
    "required": ["service"],
}


def test_preferences_name_a_tool_as_its_program_function() -> None:
    tool = CodeModeTool(
        [FakeTool("list-issues", echo, exposure=CodeModeExposure.DEFERRED)],
        cells=CodeCells(),
        limits=LIMITS,
    )
    assert tool.operation_names(7) == [
        "list_issues (a function in `execute_code` programs; find its stub with "
        "`await tool_search(query)`)"
    ]
    assert tool.operation_names(8) == []


def test_without_deferred_functions_there_is_no_tool_search() -> None:
    tool = _make_tool()
    assert "tool_search" not in tool.tool_definition().description
    result, _, _ = _run(tool, "await tool_search('x')\n")
    assert result.is_error


def test_a_deferred_function_found_with_tool_search_is_type_checked() -> None:
    tool = _make_tool(FakeMCPTool("list-tickets", _list_tickets, _TICKET_PARAMETERS))
    _, found, _ = _run(tool, "print((await tool_search('tickets'))[0]['name'])\n")
    assert found.stdout == "mcp__1__acme__list_tickets\n", found
    _, wrong, _ = _run(tool, "await mcp__1__acme__list_tickets(servise='a')\n")
    assert wrong.status == "failed"
    assert "Type check failed" in (wrong.error or ""), wrong.error
    assert wrong.calls == []
    _, right, _ = _run(
        tool, "print((await mcp__1__acme__list_tickets(service='a'))['tickets'][0])\n"
    )
    assert right.stdout == "{'id': 1, 'service': 'a'}\n", right


def test_non_citing_calls_do_not_reserve_citation_numbers() -> None:
    tool = _make_tool(FakeMCPTool("list-tickets", _list_tickets, _TICKET_PARAMETERS))
    _, details, _ = _run(
        tool,
        "import asyncio\n"
        "t, s = await asyncio.gather(mcp__1__acme__list_tickets(service='a'), "
        "web_search(queries=['x']))\n",
        ToolContext(next_citation_num=1),
    )
    assert sorted(_sources(details).citations) == [1, 2]


def test_calls_record_tool_ids_and_search_planning() -> None:
    planning = SearchPlanningResult(original_queries=("x",), searched_sources=("web",))

    def search(invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        result = _web_search(invocation, context)
        assert isinstance(result, ToolResult)
        return result.model_copy(update={"metadata": planning})

    tool = CodeModeTool([FakeWebSearchTool(search)], cells=CodeCells(), limits=LIMITS)
    _, details, events = _run(tool, "await web_search(queries=['x'])\n")
    [call] = details.calls
    assert (call.tool_id, call.metadata) == (3, planning)
    [started] = [event for event in events if isinstance(event, CodeModeCallStarted)]
    assert started.call.tool_id == 3


def test_saved_calls_are_bounded_per_call_and_per_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cells, "MAX_SAVED_CALL_CHARS", 1_000)
    monkeypatch.setattr(cells, "MIN_SAVED_CALL_CHARS", 200)
    monkeypatch.setattr(cells, "MAX_SAVED_EXECUTION_CHARS", 5_000)

    def large(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        text = str(invocation.arguments["value"]) * 10_000
        return ToolResult(
            content=json.dumps({"text": text}),
            details=CustomToolCallSummary(
                tool_name="large", response_type="json", tool_result={"text": text}
            ),
        )

    tool = _make_tool(FakeTool("large", large))
    result, details, events = _run(
        tool,
        "total = 0\n"
        "for _ in range(6):\n"
        "    r = await large(value='a')\n"
        "    total += len(r['text'])\n"
        "print(total)\n",
    )
    # The program receives every full result.
    assert "60000" in result.content
    assert len(details.calls) == 6
    for call in details.calls:
        assert len(call.content) < 1_200
        assert isinstance(call.details, CustomToolCallSummary)
        assert isinstance(call.details.tool_result, str)
        assert len(call.details.tool_result) < 1_200
        assert "characters omitted" in call.details.tool_result
    # Calls after the execution budget is spent keep less.
    assert len(details.calls[-1].content) < 400
    finished = [
        event.call for event in events if isinstance(event, CodeModeCallFinished)
    ]
    assert finished == details.calls


def _wait_for_cancellation(
    _invocation: ToolInvocation, _context: ToolContext
) -> ToolOutcome:
    """Runs until the ambient cancellation stops it, as nested LLM and HTTP work does."""
    signal = current_cancellation()
    assert signal is not None
    for _ in range(250):
        signal.check()
        time.sleep(0.02)
    return ToolResult(content="done")


SHORT_LIMITS = SandboxLimits(
    lifetime_seconds=0.5,
    max_tool_calls=20,
    max_output_chars=2_000,
    max_memory_bytes=32 * 1024 * 1024,
    max_cpu_seconds=2,
)


def test_failed_program_lists_each_call_and_warns_about_effects() -> None:
    result, details, _ = _run(
        _make_tool(FakeTool("broken", _broken)),
        "await echo(value='a')\n"
        "try:\n    await broken(value='b')\nexcept Exception:\n    pass\n"
        "1 / 0\n",
    )
    assert details.status == "failed"
    assert "[0] echo: ok\n[1] broken: error\n" in result.content
    assert "may have had effects" in result.content
    completed, _, _ = _run(_make_tool(), "await echo(value='a')\n")
    assert "[0] echo" not in completed.content


def test_timeout_stops_nested_work_and_marks_it_unfinished() -> None:
    finished = threading.Event()

    def waits(invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        try:
            return _wait_for_cancellation(invocation, context)
        finally:
            finished.set()

    tool = CodeModeTool(
        [FakeTool("echo", echo), FakeTool("waits", waits)],
        cells=CodeCells(),
        limits=SHORT_LIMITS,
    )
    started = time.monotonic()
    result, details, _ = _run(tool, "await echo(value='a')\nawait waits(value='b')\n")
    assert details.status == "timed_out"
    assert "[0] echo: ok\n[1] waits: unfinished\n" in result.content
    # The nested call ran in the program's cancellation scope, so it stops too;
    # otherwise it would run for 5 seconds.
    assert finished.wait(4)
    assert time.monotonic() - started < 4


def test_unawaited_calls_are_cancelled_and_reported() -> None:
    finished = threading.Event()

    def waits(invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        try:
            return _wait_for_cancellation(invocation, context)
        finally:
            finished.set()

    tool = CodeModeTool(
        [FakeTool("echo", echo), FakeTool("waits", waits)],
        cells=CodeCells(),
        limits=LIMITS,
    )
    started = time.monotonic()
    result, details, _ = _run(
        tool, "waits(value='a')\nawait echo(value='b')\nprint('end')\n"
    )
    assert details.status == "completed"
    assert not result.is_error
    # The program does not wait for the 5 seconds the unawaited call would run.
    assert time.monotonic() - started < 4
    assert (
        "1 tool call was started but never awaited: waits[0]. Its cancellation was "
        "requested; it may have had effects." in result.content
    )
    assert details.calls[0].state == "unfinished"
    assert finished.wait(4)


def test_failed_program_shows_type_checker_notes() -> None:
    # A type error outside tool calls does not stop the program.
    result, details, _ = _run(_make_tool(), "x: int = 'a'\n1 / 0\n")
    assert details.status == "failed"
    assert "ZeroDivisionError" in result.content
    assert "Type checker notes:\n" in result.content


def test_arguments_that_are_not_json_fail_before_the_tool_runs() -> None:
    received: list[object] = []

    def record(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        received.append(invocation.arguments)
        return ToolResult(content="{}")

    tool = CodeModeTool([FakeTool("echo", record)], cells=CodeCells(), limits=LIMITS)
    # An untyped helper keeps the type checker from rejecting the call first.
    result, details, _ = _run(
        tool, "def call(f, **kw):\n    return f(**kw)\nawait call(echo, value={1, 2})\n"
    )
    assert details.status == "failed"
    assert "The argument dict of echo() must be JSON data" in result.content
    assert "found set at ['value']" in result.content
    assert received == []
    assert details.calls == []


def test_the_tool_gets_whole_arguments_and_the_saved_call_a_bounded_copy() -> None:
    received: list[JsonValue] = []

    def record(invocation: ToolInvocation, _context: ToolContext) -> ToolOutcome:
        received.append(invocation.arguments["value"])
        return ToolResult(content="{}")

    tool = CodeModeTool([FakeTool("echo", record)], cells=CodeCells(), limits=LIMITS)
    _, details, _ = _run(
        tool,
        "big = 'x' * 100_000\n"
        "await echo(value=big)\n"
        "try:\n"
        "    await echo(value=big * 3)\n"
        "except ValueError as error:\n"
        "    print(error)\n",
    )
    assert details.status == "completed", details
    assert received == ["x" * 100_000]
    [call] = details.calls
    assert len(json_text(call.arguments)) < 2 * MAX_SAVED_CALL_CHARS
    assert details.stdout.startswith(
        "The argument dict of echo() exceeds the limit of 262144 bytes as JSON"
    )


def test_files_that_a_search_finds_reach_a_later_python_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []

    def python(_invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        seen.append([file.filename for file in context.chat_files])
        return ToolResult(content="{}")

    def search_with_files(
        invocation: ToolInvocation, context: ToolContext
    ) -> ToolOutcome:
        result = search(invocation, context)
        assert isinstance(result, ToolResult)
        assert isinstance(result.details, SearchDocsResponse)
        documents = [
            document.model_copy(update={"file_id": f"file-{document.document_id}"})
            for document in result.details.search_docs
        ]
        result.details = result.details.model_copy(update={"search_docs": documents})
        return result

    def read_files(documents: list[SearchDoc]) -> list[ChatFile]:
        return [
            ChatFile(
                filename=f"{document.document_id}.csv",
                content=b"",
                file_id=document.file_id,
            )
            for document in documents
        ]

    monkeypatch.setattr(cells, "build_python_chat_files_from_search_docs", read_files)
    tool = CodeModeTool(
        [FakeWebSearchTool(search_with_files), FakeTool(PYTHON_TOOL_NAME, python)],
        cells=CodeCells(),
        limits=LIMITS,
    )
    _, details, _ = _run(
        tool,
        "await run_python(value='before')\n"
        "await web_search(queries=['q'])\n"
        "await run_python(value='after')\n",
        ToolContext(chat_files=[ChatFile(filename="upload.txt", content=b"")]),
    )
    assert details.status == "completed", details
    assert seen == [["upload.txt"], ["upload.txt", "q-0.csv", "q-1.csv"]]


class _StagedSearch(SearchDocsResponse):
    staged: list[str]


def test_saved_calls_keep_only_the_saved_type_of_their_details() -> None:
    search = search_result(["a"], 1).details
    assert isinstance(search, SearchDocsResponse)
    staged = _StagedSearch(**dict(search), staged=["file.csv"])
    durable = durable_details(staged)
    assert type(durable) is SearchDocsResponse
    assert durable == search
    assert durable_details(Progress(step="x")) is None


def test_saving_details_leaves_the_live_structured_result() -> None:
    live = CustomToolCallSummary(
        tool_name="lookup",
        response_type="json",
        tool_result={"a": 1},
        structured_result={"a": 1},
    )
    durable_details(live)
    assert live.structured_result == {"a": 1}
