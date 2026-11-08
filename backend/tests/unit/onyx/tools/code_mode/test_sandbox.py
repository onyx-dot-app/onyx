import threading
import time
import tracemalloc
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import cast

import pytest
from prometheus_client import REGISTRY
from pydantic import JsonValue, ValidationError
from pydantic_monty import FunctionSnapshot, Monty

from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.tools.tool_implementations.code_mode import sandbox
from onyx.tools.tool_implementations.code_mode.models import (
    MAX_CPU_SECONDS,
    ExternalCall,
    ProgramSuspended,
    ProgramWaiting,
    SandboxLimits,
    SandboxResult,
    StoreSnapshot,
    TypeDiagnostic,
)
from onyx.tools.tool_implementations.code_mode.sandbox import (
    BUSY_MESSAGE,
    CRASH_MESSAGE,
    YIELD_CONTROL_STUB,
    ExternalCallHandler,
    StdoutCollector,
    execute_program,
    is_fatal_diagnostic,
    parse_type_diagnostics,
)
from onyx.tools.tool_implementations.code_mode.store import (
    STORE_STUBS,
    ProgramStore,
)
from tests.unit.onyx.tools.code_mode.fakes import until


def _count(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _worker_losses(reason: str) -> float:
    return _count("onyx_code_mode_sandbox_workers_lost_total", {"reason": reason})


def _suspensions(outcome: str) -> float:
    return _count("onyx_code_mode_suspensions_total", {"outcome": outcome})


STUBS = f"""from typing import Any, TypedDict


{STORE_STUBS}


{YIELD_CONTROL_STUB}


class Doc(TypedDict):
    title: str


async def search(*, query: str) -> list[Doc]:
    ...


async def slow(*, seconds: float) -> str:
    ...


async def fail(*, message: str) -> Any:
    ...


async def lookup(term: str) -> list[str]:
    ...
"""
FUNCTIONS = frozenset({"search", "slow", "fail"})
LIMITS = SandboxLimits(
    lifetime_seconds=10,
    max_tool_calls=5,
    max_output_chars=500,
    max_memory_bytes=32 * 1024 * 1024,
    max_cpu_seconds=1,
)


def _lookup(term: str) -> list[str]:
    if not term:
        raise ValueError("term must not be empty")
    return [f"{term} match"]


class Recorder:
    def __init__(self) -> None:
        self.calls: list[ExternalCall] = []
        self.lock = threading.Lock()

    def __call__(self, call: ExternalCall) -> object:
        with self.lock:
            self.calls.append(call)
        if call.function_name == "slow":
            seconds = call.kwargs["seconds"]
            assert isinstance(seconds, (int, float))
            time.sleep(seconds)
            return "done"
        if call.function_name == "fail":
            raise RuntimeError(str(call.kwargs["message"]))
        return [{"title": f"About {call.kwargs['query']}"}]


class Ran(SandboxResult):
    """A program's result with what a cell collects around it: the printed text,
    the store() writes, and the number of tool calls that started."""

    stdout: str = ""
    store_writes: dict[str, JsonValue] | None = None
    tool_call_count: int = 0


def run(
    code: str,
    recorder: ExternalCallHandler | None = None,
    *,
    store: StoreSnapshot | None = None,
    limits: SandboxLimits = LIMITS,
    cancellation: CancellationSignal | None = None,
    on_stdout: Callable[[str], None] | None = None,
    on_yield: Callable[[], None] = lambda: None,
    pool: Monty | None = None,
) -> Ran:
    collector = StdoutCollector(
        limits.max_output_chars, live_chars=limits.max_output_chars
    )
    program_store = ProgramStore(store or StoreSnapshot(values={}))
    handler = recorder or Recorder()
    started: list[ExternalCall] = []

    def on_print(text: str) -> None:
        live = collector.write(text)
        if live and on_stdout is not None:
            on_stdout(live)

    def counted(call: ExternalCall) -> object:
        started.append(call)
        return handler(call)

    result = execute_program(
        code,
        stubs=STUBS,
        function_names=FUNCTIONS,
        plain_functions=program_store.functions,
        async_functions={"lookup": _lookup},
        handler=counted,
        limits=limits,
        cancellation=cancellation or CancellationSignal(),
        on_print=on_print,
        on_yield=on_yield,
        **({"pool": lambda: pool} if pool is not None else {}),
    )
    return Ran(
        **dict(result),
        stdout=collector.text,
        store_writes=program_store.writes,
        tool_call_count=len(started),
    )


def test_gather_runs_tool_calls_in_parallel() -> None:
    recorder = Recorder()
    started = time.monotonic()
    result = run(
        "import asyncio\n"
        "out = await asyncio.gather(*[slow(seconds=1) for _ in range(4)])\n"
        "print(len(out))\n"
        "out",
        recorder,
    )
    elapsed = time.monotonic() - started
    assert result.status == "completed", result
    assert result.stdout == "4\n"
    assert result.result == "['done', 'done', 'done', 'done']"
    assert result.tool_call_count == 4
    assert sorted(call.index for call in recorder.calls) == [0, 1, 2, 3]
    # In sequence the calls would take 4 seconds.
    assert elapsed < 3


def test_positional_arguments_are_rejected() -> None:
    # Untyped parameters hide the call from the type checker; the runtime rejects it.
    result = run("def call(f, *args):\n    return f(*args)\nawait call(search, 'x')\n")
    assert result.status == "failed"
    assert result.error is not None
    assert "keyword arguments only" in result.error


def test_functions_import_like_a_module() -> None:
    recorder = Recorder()
    result = run(
        "from functions import search\n"
        "import functions\n"
        "a = await search(query='a')\n"
        "b = await functions.search(query='b')\n"
        "functions.store('k', 1)\n"
        "print(a[0]['title'], b[0]['title'])",
        recorder,
    )
    assert result.status == "completed", result
    assert result.stdout == "About a About b\n"
    assert [call.function_name for call in recorder.calls] == ["search", "search"]
    assert result.store_writes == {"k": 1}


def test_other_imports_still_fail() -> None:
    result = run("import requests")
    assert result.status == "failed"
    assert result.error is not None and "requests" in result.error


def test_unknown_function_is_a_name_error() -> None:
    result = run("missing_tool(query='x')\n")
    assert result.status == "failed"
    assert result.error is not None
    assert "NameError: name 'missing_tool' is not defined" in result.error


def test_type_error_in_tool_call_stops_before_any_tool_runs() -> None:
    recorder = Recorder()
    result = run("await slow(seconds=0.1)\nawait search(qurey='x')\n", recorder)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.startswith("Type check failed; the program did not run.")
    assert "unknown-argument" in result.error
    assert recorder.calls == []


def test_non_tool_type_errors_do_not_stop_the_program() -> None:
    # Rebinding a name to another type is valid Python but a type error.
    result = run("docs = await search(query='a')\ndocs = None\nprint(docs)\n")
    assert result.status == "completed"
    assert result.stdout == "None\n"


def test_cpu_limit() -> None:
    result = run("while True:\n    pass\n")
    assert result.status == "timed_out"
    assert "feed time limit exceeded" in (result.error or "")


@pytest.mark.parametrize(
    "statement",
    [
        "raise RuntimeError('time limit exceeded')",
        "raise TimeoutError('feed time limit exceeded')",
    ],
)
def test_program_errors_that_mention_a_time_limit_are_failures(
    statement: str,
) -> None:
    result = run(f"{statement}\n")
    assert result.status == "failed", result
    assert "time limit exceeded" in (result.error or "")


def test_memory_limit() -> None:
    result = run("data = 'x' * (64 * 1024 * 1024)\n")
    assert result.status == "failed"
    assert result.error is not None
    assert "MemoryError" in result.error


def test_tool_call_limit() -> None:
    result = run("for i in range(10):\n    await search(query=str(i))\n")
    assert result.status == "failed"
    assert result.tool_call_count == 5
    assert result.error is not None
    assert "Tool call limit reached" in result.error


def test_handler_base_exception_propagates() -> None:
    def handler(_call: ExternalCall) -> object:
        raise AgentCancelled()

    with pytest.raises(AgentCancelled):
        run("await search(query='x')\n", handler)


def test_each_execution_starts_with_a_fresh_interpreter() -> None:
    assert run("docs = await search(query='a')\nimport json\n").status == "completed"
    result = run("docs\n")
    assert result.status == "failed"
    assert result.error is not None
    assert "NameError" in result.error
    assert "NameError" in (run("json.dumps(1)\n").error or "")


def test_store_and_load() -> None:
    result = run(
        "print(load('missing'))\n"
        "print(load('old'))\n"
        "store('docs', [{'title': 't', 'n': 1.5, 'ok': True, 'tags': ('a', 'b')}])\n"
        "store(key='old', value=None)\n"
        "print(load('docs'), load('old'))\n"
        "d = load('docs')\n"
        "d.append(2)\n"
        "print(len(load('docs')))\n",
        store=StoreSnapshot(values={"old": "value"}),
    )
    assert result.status == "completed", result
    assert result.stdout == (
        "None\n"
        "value\n"
        "[{'title': 't', 'n': 1.5, 'ok': True, 'tags': ['a', 'b']}] None\n"
        "1\n"
    )
    assert result.store_writes == {
        "docs": [{"title": "t", "n": 1.5, "ok": True, "tags": ["a", "b"]}],
        "old": None,
    }


UNTYPED_CALL = "def call(f, *args):\n    return f(*args)\n"


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        ("store('k', {1, 2})", 'Cannot store "k": the value must be JSON data'),
        ("store('k', {1: 'a'})", "dict keys must be str"),
        ("store('k', [float('nan')])", "not a JSON number"),
        ("store('k', float('inf'))", "not a JSON number"),
        ("store('k', {'a': [b'x']})", "found bytes at ['a'][0]"),
        (
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class P:\n"
            "    x: int\n"
            "store('k', {'p': P(1)})",
            "found P at ['p']",
        ),
        ("store(json.loads('1'), 'v')", "Store keys must be str"),
        ("store('', 'v')", "Store keys must have 1 to"),
        ("call(store, 'k')", "missing a required argument: 'value'"),
        ("call(load, 'k', 'extra')", "too many positional arguments"),
    ],
)
def test_store_rejects_invalid_values_and_keys(statement: str, message: str) -> None:
    # The untyped helpers keep the type checker from rejecting the calls first.
    result = run(f"import json\n{UNTYPED_CALL}{statement}\n")
    assert result.status == "failed", result
    assert result.error is not None
    assert message in result.error


def test_invalid_store_value_can_be_caught() -> None:
    result = run(
        "try:\n"
        "    store('k', {1, 2})\n"
        "except TypeError as error:\n"
        "    print('caught')\n"
    )
    assert result.status == "completed"
    assert result.stdout == "caught\n"
    assert result.store_writes == {}


def test_store_size_limits() -> None:
    value_limit = run("store('k', 'x' * (300 * 1024))\n")
    assert value_limit.status == "failed"
    assert "exceeds the limit of 262144 bytes as JSON" in (value_limit.error or "")

    full = {f"k{i}": "x" * (200 * 1024) for i in range(5)}
    total_limit = run(
        "store('more', 'x' * (100 * 1024))\n", store=StoreSnapshot(values=full)
    )
    assert total_limit.status == "failed"
    assert "the limit is 1048576 bytes" in (total_limit.error or "")

    # Replacing or deleting keys of a full store is allowed.
    shrink = run(
        "store('k0', 'small')\nstore('k1', None)\n", store=StoreSnapshot(values=full)
    )
    assert shrink.status == "completed", shrink


def test_shared_references_are_rejected_inside_the_program() -> None:
    # Each step doubles the JSON size of `x` at no cost to the program: 2**25
    # leaves. The host copies stop at their byte limits.
    tracemalloc.start()
    started = time.monotonic()
    try:
        result = run(
            "x = [1]\n"
            "for _ in range(25):\n"
            "    x = [x, x]\n"
            "try:\n"
            "    store('k', x)\n"
            "except ValueError as error:\n"
            "    print(error)\n"
            "x\n"
        )
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert time.monotonic() - started < 5
    assert peak_bytes < 64 * 1024 * 1024
    assert result.status == "completed", result
    assert result.stdout.startswith(
        'Cannot store "k": the value exceeds the limit of 262144 bytes as JSON'
    )
    assert result.result is None
    assert result.error is not None
    assert result.error.startswith(
        "The value of the last expression exceeds the limit of 500 bytes as JSON"
    )
    assert result.store_writes == {}


def test_deep_values_are_rejected_inside_the_program() -> None:
    result = run(
        "y = []\n"
        "for _ in range(1200):\n"
        "    y = [y, y]\n"
        "try:\n"
        "    store('k', y)\n"
        "except ValueError as error:\n"
        "    print(error)\n"
        "y\n"
    )
    assert result.status == "completed", result
    assert result.stdout.startswith(
        'Cannot store "k": the value nests more than 100 levels deep at [0][0]'
    )
    assert "nests more than 100 levels deep" in (result.error or "")


def test_a_result_that_is_not_json_data_is_reported() -> None:
    result = run("({1, 2}, 'kept')\n")
    assert result.status == "completed", result
    assert result.result is None
    assert "found set at [0]" in (result.error or "")
    assert run("(1, 'a', None)\n").result == "[1, 'a', None]"


def test_limits_must_be_positive_and_within_the_compute_cap() -> None:
    with pytest.raises(ValidationError):
        SandboxLimits(max_cpu_seconds=MAX_CPU_SECONDS + 1)
    with pytest.raises(ValidationError):
        SandboxLimits(max_tool_calls=0)


def test_writes_commit_when_the_program_ends_by_itself() -> None:
    completed = run("store('k', 1)\n")
    raised = run("store('k', 1)\nraise ValueError('x')\n")
    not_type_checked = run("store('k', 1)\nawait search(query=1)\n")
    cancellation = CancellationSignal()
    threading.Timer(0.3, cancellation.cancel).start()
    cancelled = run(
        "import asyncio\nstore('k', 1)\nawait asyncio.sleep(30)\n",
        cancellation=cancellation,
    )
    assert [r.status for r in (completed, raised, not_type_checked, cancelled)] == [
        "completed",
        "failed",
        "failed",
        "cancelled",
    ]
    assert raised.store_writes == {"k": 1}
    assert [
        r.commits_store for r in (completed, raised, not_type_checked, cancelled)
    ] == [True, True, False, False]


def test_awaiting_load_fails() -> None:
    result = run("await load('k')\n")
    assert result.status == "failed"
    assert "can't be awaited" in (result.error or "")


def test_stdout_streams_and_is_cut_once_with_an_exact_count() -> None:
    chunks: list[str] = []
    result = run(
        "for i in range(2000):\n    print('line', i)\n", on_stdout=chunks.append
    )
    printed = sum(len(f"line {i}\n") for i in range(2000))
    assert result.status == "completed"
    assert result.stdout.startswith("line 0\n")
    assert result.stdout.endswith("line 1999\n")
    assert result.stdout.count("characters omitted") == 1
    omitted = printed - LIMITS.max_output_chars
    assert f"[output truncated, {omitted} characters omitted]" in result.stdout
    streamed = "".join(chunks)
    assert streamed.startswith("line 0\n")
    assert "further output is not shown live" in streamed
    assert len(streamed) < 700


COMPUTE_LIMITS = SandboxLimits(
    lifetime_seconds=10,
    max_tool_calls=5,
    max_output_chars=500,
    max_memory_bytes=32 * 1024 * 1024,
    max_cpu_seconds=20,
)


def test_stop_during_computation_kills_the_worker(two_workers: Monty) -> None:
    killed = _worker_losses("killed")
    cancellation = CancellationSignal()
    threading.Timer(0.2, cancellation.cancel).start()
    started = time.monotonic()
    result = run(
        "while True:\n    pass\n",
        limits=COMPUTE_LIMITS,
        cancellation=cancellation,
        pool=two_workers,
    )
    assert result.status == "cancelled", result
    assert _worker_losses("killed") == killed + 1
    assert result.error == "The execution was cancelled."
    # Far less than the compute limit.
    assert time.monotonic() - started < 5
    # The pool replaces the killed worker.
    assert run("print(1)\n", pool=two_workers).stdout == "1\n"


def test_wall_clock_timeout_during_computation(two_workers: Monty) -> None:
    started = time.monotonic()
    result = run(
        "await search(query='a')\nwhile True:\n    pass\n",
        limits=SandboxLimits(
            lifetime_seconds=0.3,
            max_tool_calls=5,
            max_output_chars=500,
            max_memory_bytes=32 * 1024 * 1024,
            max_cpu_seconds=20,
        ),
        pool=two_workers,
    )
    assert result.status == "timed_out", result
    assert "did not finish within 0.3 seconds" in (result.error or "")
    assert result.tool_call_count == 1
    assert time.monotonic() - started < 5
    assert run("print(2)\n", pool=two_workers).stdout == "2\n"


def test_file_access_is_denied() -> None:
    result = run("open('/etc/passwd').read()\n")
    assert result.status == "failed"
    assert result.error is not None
    assert "PermissionError" in result.error


def test_fatal_diagnostics_are_only_tool_call_errors() -> None:
    diagnostics = parse_type_diagnostics(
        "main.py:1:7: error[unknown-argument] Argument `q` does not match any known "
        "parameter of function `search`\n"
        "main.py:2:1: error[unresolved-reference] Name `x` used when not defined\n"
        "main.py:3:1: error[invalid-argument-type] Argument to function `len` is "
        "incorrect\n"
    )
    assert [d.code for d in diagnostics] == [
        "unknown-argument",
        "unresolved-reference",
        "invalid-argument-type",
    ]
    assert [is_fatal_diagnostic(d, FUNCTIONS) for d in diagnostics] == [
        True,
        False,
        False,
    ]
    syntax = TypeDiagnostic(code="invalid-syntax", message="Expected `)`", line="")
    assert is_fatal_diagnostic(syntax, FUNCTIONS)


@pytest.fixture(scope="module")
def two_workers() -> Iterator[Monty]:
    with Monty(
        min_processes=1,
        max_processes=2,
        checkout_timeout=sandbox.CHECKOUT_POLL_SECONDS,
    ) as pool:
        yield pool


def test_programs_return_their_worker_while_tools_run(two_workers: Monty) -> None:
    programs = 16
    seconds = 0.5

    def execute(index: int) -> Ran:
        return run(
            f"store('i', {index})\n"
            "a = await slow(seconds=0.5)\n"
            "b = await slow(seconds=0.5)\n"
            "print(a, b, load('i'))\n",
            pool=two_workers,
        )

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=programs) as executor:
        results = list(executor.map(execute, range(programs)))
    elapsed = time.monotonic() - started
    assert [result.stdout for result in results] == [
        f"done done {index}\n" for index in range(programs)
    ], results
    # Holding a worker through both calls would take programs * seconds in total.
    assert elapsed < programs * seconds * 0.75, elapsed


def test_a_waiting_program_keeps_its_worker_while_no_other_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dumps: list[int] = []
    suspend = sandbox._suspend

    def counted(run: sandbox._Run, waiting: ProgramWaiting) -> ProgramSuspended | None:
        dumps.append(1)
        return suspend(run, waiting)

    monkeypatch.setattr(sandbox, "_suspend", counted)
    result = run(
        "a = await slow(seconds=0.1)\nb = await slow(seconds=0.1)\nprint(a, b)\n"
    )
    assert (result.status, result.stdout) == ("completed", "done done\n")
    assert dumps == []


def test_a_dump_over_the_byte_budget_keeps_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox, "_suspended_bytes", sandbox._SuspendedBytes(0))
    over_budget = _suspensions("over_budget")
    dumped = _suspensions("dumped")
    with Monty(
        min_processes=1, max_processes=1, checkout_timeout=sandbox.CHECKOUT_POLL_SECONDS
    ) as pool:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda index: run(
                        f"print(await slow(seconds=0.5), {index})\n", pool=pool
                    ),
                    range(2),
                )
            )
    assert [result.stdout for result in results] == ["done 0\n", "done 1\n"]
    assert _suspensions("over_budget") > over_budget
    assert _suspensions("dumped") == dumped


def test_a_dump_that_cannot_fit_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "_suspended_bytes", sandbox._SuspendedBytes(10))

    class Snapshot:
        dumps = 0

        def dump(self) -> bytes:
            Snapshot.dumps += 1
            return b"x" * 100

    run_state = sandbox._Run(
        limits=LIMITS,
        function_names=FUNCTIONS,
        plain_functions={},
        async_functions={},
        handler=lambda _call: None,
        cancellation=CancellationSignal(),
        on_print=lambda _text: None,
        on_yield=lambda: None,
    )
    # A fake snapshot: skip the isinstance validation.
    waiting = ProgramWaiting.model_construct(state=cast(FunctionSnapshot, Snapshot()))
    assert sandbox._suspend(run_state, waiting) is None
    assert sandbox._suspend(run_state, waiting) is None
    # The second dump is skipped: the first did not fit.
    assert Snapshot.dumps == 1


def test_each_waiting_program_claims_one_holder() -> None:
    demand = sandbox._WorkerDemand(2)
    woken: list[str] = []

    def first() -> None:
        woken.append("first")

    def second() -> None:
        woken.append("second")

    with demand.holding(first), demand.holding(second):
        with demand.waiting():
            assert woken == ["first"]
            # A repeated claim adds none while the claim stands.
            demand.claim()
            assert woken == ["first"]
        # The waiter left before the holder gave up: the claim is withdrawn.
        assert not demand.gives_up(first)
        with demand.waiting(), demand.waiting():
            assert woken == ["first", "first", "second"]
            assert demand.gives_up(first) and demand.gives_up(second)


def _slow_counted_dumps(monkeypatch: pytest.MonkeyPatch, seconds: float) -> list[int]:
    dumps: list[int] = []
    suspend = sandbox._suspend

    def slow_dump(
        run: sandbox._Run, waiting: ProgramWaiting
    ) -> ProgramSuspended | None:
        dumps.append(1)
        time.sleep(seconds)
        return suspend(run, waiting)

    monkeypatch.setattr(sandbox, "_suspend", slow_dump)
    return dumps


@contextmanager
def _holders(
    demand: sandbox._WorkerDemand, pool: Monty, holders: int
) -> Iterator[list[Ran]]:
    """Run `holders` programs that keep their worker while a tool runs."""
    results: list[Ran] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                run("print(await slow(seconds=3))\n", pool=pool)
            )
        )
        for _ in range(holders)
    ]
    for thread in threads:
        thread.start()
    until(lambda: len(demand._holders) == holders)
    yield results
    for thread in threads:
        thread.join()


def test_a_waiting_program_dumps_one_holder(
    monkeypatch: pytest.MonkeyPatch, two_workers: Monty
) -> None:
    demand = sandbox._WorkerDemand(2)
    monkeypatch.setattr(sandbox, "_worker_demand", demand)
    # The dump outlasts the waiter's checkout retries.
    dumps = _slow_counted_dumps(monkeypatch, 3 * sandbox.CHECKOUT_POLL_SECONDS)
    dumped = _suspensions("dumped")
    with _holders(demand, two_workers, 2) as results:
        assert run("print(1)\n", pool=two_workers).stdout == "1\n"
    assert [result.stdout for result in results] == ["done\n", "done\n"]
    assert dumps == [1]
    assert _suspensions("dumped") == dumped + 1


def test_a_program_that_finds_every_worker_busy_claims_one_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    demand = sandbox._WorkerDemand(1)
    monkeypatch.setattr(sandbox, "_worker_demand", demand)
    dumps = _slow_counted_dumps(monkeypatch, 0)
    with Monty(min_processes=1, max_processes=1, checkout_timeout=2) as pool:
        with _holders(demand, pool, 1) as results:
            started = time.monotonic()
            assert run("print(1)\n", pool=pool).stdout == "1\n"
            # Far less than the pool's checkout timeout.
            assert time.monotonic() - started < 1.5
    assert [result.stdout for result in results] == ["done\n"]
    assert dumps == [1]


def test_program_state_and_store_survive_a_released_wait() -> None:
    result = run(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "    def doubled(self):\n"
        "        return self.x * 2\n"
        "p = Point(3)\n"
        "f = slow\n"
        "store('a', 1)\n"
        "print('before')\n"
        "r = await f(seconds=0.1)\n"
        "store('b', load('a') + 1)\n"
        "print('after', p.doubled(), r, load('b'))\n",
    )
    assert result.status == "completed", result
    assert result.stdout == "before\nafter 6 done 2\n"
    assert result.store_writes == {"a": 1, "b": 2}


def test_cancellation_during_a_released_wait(two_workers: Monty) -> None:
    cancellation = CancellationSignal()
    threading.Timer(0.3, cancellation.cancel).start()
    started = time.monotonic()
    result = run(
        "store('k', 1)\nawait slow(seconds=30)\n",
        cancellation=cancellation,
        pool=two_workers,
    )
    assert result.status == "cancelled"
    assert time.monotonic() - started < 10


def test_crashed_worker_reports_the_crash_and_keeps_output() -> None:
    # The pool kills a worker that runs past its request timeout.
    with Monty(min_processes=1, max_processes=1, request_timeout=0.5) as pool:
        result = run(
            "print('before')\nstore('k', 1)\nawait search(query='a')\n"
            "while True:\n    pass\n",
            limits=COMPUTE_LIMITS,
            pool=pool,
        )
    assert result.status == "timed_out", result
    assert result.error == CRASH_MESSAGE
    assert result.stdout == "before\n"
    assert result.tool_call_count == 1


def test_busy_pool_fails_without_running_the_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox, "CHECKOUT_TIMEOUT_SECONDS", 0.5)
    with Monty(min_processes=1, max_processes=1, checkout_timeout=0.1) as pool:
        with pool.checkout():
            recorder = Recorder()
            result = run("await search(query='x')\n", recorder, pool=pool)
    assert result.status == "failed"
    assert result.error == BUSY_MESSAGE
    assert recorder.calls == []


def test_stop_while_waiting_for_a_worker() -> None:
    with Monty(min_processes=1, max_processes=1, checkout_timeout=0.1) as pool:
        with pool.checkout():
            cancellation = CancellationSignal()
            threading.Timer(0.3, cancellation.cancel).start()
            recorder = Recorder()
            started = time.monotonic()
            result = run(
                "await search(query='x')\n",
                recorder,
                cancellation=cancellation,
                pool=pool,
            )
    assert result.status == "cancelled", result
    assert result.error == "The execution was cancelled."
    # Far less than the checkout timeout.
    assert time.monotonic() - started < 5
    assert recorder.calls == []


def test_duration_excludes_waiting_for_a_worker() -> None:
    with Monty(min_processes=1, max_processes=1, checkout_timeout=10) as pool:
        busy = threading.Event()

        def hold_the_worker() -> None:
            with pool.checkout():
                busy.set()
                time.sleep(1)

        holder = threading.Thread(target=hold_the_worker)
        holder.start()
        assert busy.wait(5)
        started = time.monotonic()
        result = run("print(1)\n", pool=pool)
        waited = time.monotonic() - started
        holder.join()
    assert result.status == "completed"
    assert waited > 0.5
    # The run's duration leaves out most of the wait for the worker.
    assert result.duration_seconds < waited - 0.3


def test_sleeping_programs_return_their_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A program that waits longer than this for the only worker fails as busy.
    monkeypatch.setattr(sandbox, "CHECKOUT_TIMEOUT_SECONDS", 1.0)
    sleep = 2
    printed = {marker: threading.Event() for marker in "abc"}

    def on_stdout(text: str) -> None:
        for marker in text.split():
            printed[marker].set()

    with Monty(min_processes=1, max_processes=1, checkout_timeout=0.1) as pool:
        with ThreadPoolExecutor(max_workers=1) as executor:
            sleeper = executor.submit(
                run,
                "import time, asyncio\n"
                "print('a')\n"
                f"time.sleep({sleep})\n"
                "print('b')\n"
                f"await asyncio.sleep({sleep})\n"
                "print('c')\n",
                pool=pool,
                on_stdout=on_stdout,
            )
            assert printed["a"].wait(10)
            during_sync = run("print(1)\n", pool=pool)
            assert printed["b"].wait(10)
            during_async = run("print(2)\n", pool=pool)
            slept = sleeper.result()
    assert during_sync.stdout == "1\n", during_sync
    assert during_async.stdout == "2\n", during_async
    assert slept.status == "completed", slept
    assert slept.stdout == "a\nb\nc\n"
    assert slept.duration_seconds >= 2 * sleep


def test_parallel_sleeps_start_no_threads() -> None:
    threads_before = threading.active_count()
    peak = threads_before
    finished = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not finished.wait(0.01):
            peak = max(peak, threading.active_count())

    sampler = threading.Thread(target=sample)
    sampler.start()
    try:
        started = time.monotonic()
        result = run(
            "import asyncio\n"
            "await asyncio.gather(*[asyncio.sleep(0.3) for _ in range(400)])\n"
            "print('slept')\n"
        )
        elapsed = time.monotonic() - started
    finally:
        finished.set()
        sampler.join()
    assert result.status == "completed", result
    assert result.stdout == "slept\n"
    # In sequence the sleeps would take 120 seconds.
    assert elapsed < 10
    # No thread per sleep; other threads (the sampler, the watchdog, pool upkeep)
    # stay far below one per sleep.
    assert peak < threads_before + 20


def test_sleep_ends_at_the_wall_clock_limit() -> None:
    started = time.monotonic()
    result = run(
        "import time\ntime.sleep(60)\n",
        limits=SandboxLimits(
            lifetime_seconds=0.5,
            max_tool_calls=5,
            max_output_chars=500,
            max_memory_bytes=32 * 1024 * 1024,
            max_cpu_seconds=1,
        ),
    )
    assert result.status == "timed_out", result
    assert time.monotonic() - started < 10


def test_yield_control_returns_at_once_and_the_program_continues() -> None:
    yields: list[float] = []
    started = time.monotonic()
    result = run(
        "print('a')\nyield_control()\nprint('b')\n",
        on_yield=lambda: yields.append(time.monotonic() - started),
    )
    assert result.status == "completed", result
    assert result.stdout == "a\nb\n"
    assert len(yields) == 1


def test_yield_control_takes_no_arguments() -> None:
    # The type checker stops a direct call; the host rejects an indirect one.
    assert "`yield_control`" in (run("yield_control(1)\n").error or "")
    result = run("def call(f, *args):\n    return f(*args)\ncall(yield_control, 1)\n")
    assert result.status == "failed"
    assert "yield_control(): too many positional arguments" in (result.error or "")


def test_sleeps_reach_the_host_unclamped(monkeypatch: pytest.MonkeyPatch) -> None:
    # The cell's lifetime bounds sleeps; Monty's per-sleep cap must not shorten them.
    requested: list[float] = []
    measure = sandbox._sleep_seconds

    def record(call: FunctionSnapshot) -> float:
        requested.append(measure(call))
        return 0.0

    monkeypatch.setattr(sandbox, "_sleep_seconds", record)
    # A new pool: a warm worker keeps the OS policy of its first checkout.
    with Monty(min_processes=1, max_processes=1) as pool:
        result = run(
            "import asyncio, time\nawait asyncio.sleep(600)\ntime.sleep(700)\n",
            pool=pool,
        )
    assert result.status == "completed", result
    assert requested == [600.0, 700.0]


def test_tool_calls_beyond_the_concurrency_limit_wait_for_a_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox, "MAX_CONCURRENT_TOOL_CALLS", 2)
    lock = threading.Lock()
    active = 0
    most = 0

    def handler(_call: ExternalCall) -> object:
        nonlocal active, most
        with lock:
            active += 1
            most = max(most, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        return "done"

    result = run(
        "import asyncio\n"
        "print(await asyncio.gather(*(slow(seconds=0) for _ in range(5))))\n",
        handler,
    )
    assert result.status == "completed", result
    assert result.stdout == "['done', 'done', 'done', 'done', 'done']\n"
    assert most == 2


def test_a_resumed_program_waits_for_a_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sandbox, "CHECKOUT_TIMEOUT_SECONDS", 0.3)
    with Monty(min_processes=1, max_processes=1, checkout_timeout=0.1) as pool:
        held = threading.Event()

        def hold_the_worker() -> None:
            # Waits for the worker as programs do, so the waiting program gives
            # it up.
            with sandbox._worker_demand.waiting():
                while True:
                    try:
                        with pool.checkout():
                            held.set()
                            time.sleep(1)
                            return
                    except TimeoutError:
                        continue

        def handler(_call: ExternalCall) -> object:
            # The only worker is busy for longer than a new program would wait.
            threading.Thread(target=hold_the_worker).start()
            assert held.wait(5)
            return "done"

        result = run("print(await slow(seconds=0))\n", handler, pool=pool)
    assert result.status == "completed", result
    assert result.stdout == "done\n"


def test_tool_calls_wait_for_a_free_process_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no free tool call thread in the process, calls wait; they do not fail."""
    monkeypatch.setattr(sandbox, "_tool_call_threads", sandbox._ToolCallThreads(2))
    lock = threading.Lock()
    active = 0
    most = 0

    def handler(_call: ExternalCall) -> object:
        nonlocal active, most
        with lock:
            active += 1
            most = max(most, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return "done"

    programs = [
        "import asyncio\n"
        "print(len(await asyncio.gather(*(slow(seconds=0) for _ in range(3)))))\n"
    ] * 2
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda code: run(code, handler), programs))
    assert [(result.status, result.stdout) for result in results] == [
        ("completed", "3\n"),
        ("completed", "3\n"),
    ]
    assert most == 2


def test_a_call_that_outlives_its_program_keeps_its_thread_until_it_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads = sandbox._ToolCallThreads(1)
    monkeypatch.setattr(sandbox, "_tool_call_threads", threads)
    release = threading.Event()

    def handler(_call: ExternalCall) -> object:
        release.wait(5)
        return "late"

    result = run("pending = slow(seconds=1)\n'started'\n", handler)
    assert result.status == "completed", result
    assert [call.function_name for call in result.unawaited_calls] == ["slow"]
    # The unawaited call still holds the only thread, and the gauge shows it.
    assert not threads.acquire(lambda: None)
    assert _held_after_end() == 1
    release.set()
    until(lambda: threads.acquire(lambda: None))
    assert _held_after_end() == 0


def _held_after_end() -> float:
    return (
        REGISTRY.get_sample_value("onyx_code_mode_tool_call_threads_held_after_end")
        or 0.0
    )


def test_queued_calls_that_never_started_are_not_reported_as_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads = sandbox._ToolCallThreads(1)
    monkeypatch.setattr(sandbox, "_tool_call_threads", threads)
    release = threading.Event()

    def handler(_call: ExternalCall) -> object:
        release.wait(5)
        return "late"

    result = run("a = slow(seconds=1)\nb = slow(seconds=2)\n'started'\n", handler)
    release.set()
    assert result.status == "completed", result
    assert [call.index for call in result.unawaited_calls] == [0]
    assert [call.index for call in result.unstarted_calls] == [1]


def test_programs_waiting_for_threads_share_them_equally() -> None:
    threads = sandbox._ToolCallThreads(4)

    def first() -> None:
        pass

    def second() -> None:
        pass

    # Alone, a program may take every thread.
    assert all(threads.acquire(first) for _ in range(4))
    assert not threads.acquire(second)
    threads.release(first)
    # The released thread goes to the waiting program, not back to the first,
    # which already holds more than its share.
    assert not threads.acquire(first)
    assert threads.acquire(second)


def test_an_async_host_function_answers_when_awaited_without_a_tool_call() -> None:
    recorder = Recorder()
    result = run(
        "import asyncio\n"
        "found, docs = await asyncio.gather(lookup('alpha'), search(query='q'))\n"
        "print(found, docs[0]['title'])\n"
        "try:\n"
        "    await lookup('')\n"
        "except ValueError as error:\n"
        "    print('rejected:', error)\n",
        recorder,
    )
    assert result.status == "completed", result.error
    assert result.stdout == (
        "['alpha match'] About q\nrejected: term must not be empty\n"
    )
    assert [call.function_name for call in recorder.calls] == ["search"]
    assert result.tool_call_count == 1
