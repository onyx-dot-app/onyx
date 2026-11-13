import threading
import time
import tracemalloc
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, nullcontext
from functools import partial
from pathlib import Path
from typing import cast

import pytest
from prometheus_client import REGISTRY
from pydantic import JsonValue, ValidationError
from pydantic_monty import FunctionSnapshot, Monty, MontySession, SyncSnapshot

from onyx.llm.cancellation import AgentCancelled, CancellationSignal
from onyx.tools.tool_implementations.code_mode import sandbox
from onyx.tools.tool_implementations.code_mode.models import (
    MAX_CPU_SECONDS,
    ExternalCall,
    ProgramCompleted,
    ProgramStopped,
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
    PRELUDE_STUBS,
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
from onyx.utils.timing import PausableClock
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.unit.onyx.tools.code_mode.fakes import until


def _count(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _worker_losses(reason: str) -> float:
    return _count("onyx_code_mode_sandbox_workers_lost_total", {"reason": reason})


def _suspensions(outcome: str) -> float:
    return _count("onyx_code_mode_suspensions_total", {"outcome": outcome})


STUBS = f"""from typing import Any, TypedDict


{PRELUDE_STUBS}


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
# The default memory limit: a waiting program dumps only while its worker holds
# less than a share of it.
LIMITS = SandboxLimits(
    lifetime_seconds=10,
    max_tool_calls=5,
    max_output_chars=500,
    max_result_bytes=2_000,
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
        clock=PausableClock(),
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
    result = run("data = 'x' * (256 * 1024 * 1024)\n")
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
    assert run("docs = await search(query='a')\njson = 1\n").status == "completed"
    result = run("docs\n")
    assert result.status == "failed"
    assert result.error is not None
    assert "NameError" in result.error
    assert run("json.dumps(1)\n").result == "'1'"


def test_allowed_modules_are_imported_in_every_program(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostics: list[str] = []
    parse = sandbox.parse_type_diagnostics

    def recorded(text: str) -> list[TypeDiagnostic]:
        diagnostics.append(text)
        return parse(text)

    monkeypatch.setattr(sandbox, "parse_type_diagnostics", recorded)
    code = (
        "async def double(x):\n"
        "    return x * 2\n"
        "values = await asyncio.gather(double(1), double(2))\n"
        "text = json.dumps(values)\n"
        "print(re.sub('[0-9]', 'n', text))\n"
    )
    ran = run(code)
    assert (ran.status, ran.stdout) == ("completed", "[n, n]\n"), ran
    # The type checker knows the modules too.
    assert diagnostics == []
    # A traceback gives the program's own line numbers.
    failed = run(code + "raise ValueError('stop')\n")
    assert "line 6" in (failed.error or ""), failed.error
    explicit = run("import json\nfrom json import dumps\n[json.dumps(1), dumps(2)]\n")
    assert explicit.result == "['1', '2']", explicit


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
        "The value of the last expression exceeds the limit of 2000 bytes as JSON"
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


def test_the_result_limits_bytes_of_the_copy_and_characters_of_its_repr() -> None:
    # 800 bytes as JSON, 402 characters as repr: within both limits.
    assert run("'é' * 400\n").result == repr("é" * 400)
    cut = run("'é' * 900\n")
    assert cut.status == "completed", cut
    assert cut.result is not None and "é" * 100 in cut.result
    assert len(cut.result) < 1_000


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


_DENIED = "PermissionError"
_UNRESOLVED_IMPORT = "Cannot resolve imported module"
_NO_ATTRIBUTE = "AttributeError: module"


@pytest.mark.parametrize(
    ("code", "error", "result"),
    [
        # File system, environment and process functions are denied.
        ("os.environ\n", _DENIED, None),
        ("os.getenv('HOME')\n", _DENIED, None),
        ("os.listdir('/')\n", _DENIED, None),
        ("os.remove('/tmp/x')\n", _DENIED, None),
        ("open('/etc/passwd').read()\n", _DENIED, None),
        ("pathlib.Path('/etc/passwd').read_text()\n", _DENIED, None),
        ("pathlib.Path('/etc/passwd').exists()\n", _DENIED, None),
        # Other modules do not exist.
        ("import subprocess\n", _UNRESOLVED_IMPORT, None),
        ("import socket\n", _UNRESOLVED_IMPORT, None),
        ("import ctypes\n", _UNRESOLVED_IMPORT, None),
        ("__import__('os')\n", "NameError: name '__import__' is not defined", None),
        ("exec('import subprocess')\n", "No module named 'subprocess'", None),
        ("().__class__.__bases__[0].__subclasses__()\n", "AttributeError", None),
        ("os.system('id')\n", _NO_ATTRIBUTE, None),
        ("os.getpid()\n", _NO_ATTRIBUTE, None),
        ("sys.exit(0)\n", _NO_ATTRIBUTE, None),
        # Monty's fixed values, nothing from the host.
        ("os.getcwd()\n", None, "'/'"),
        ("sys.version\n", None, "'3.14.0 (Monty)'"),
        ("sys.argv\n", None, "['main.py']"),
    ],
)
def test_programs_cannot_reach_the_host(
    code: str, error: str | None, result: str | None
) -> None:
    ran = run(f"import os, pathlib, sys\n{code}")
    if error is None:
        assert (ran.status, ran.result) == ("completed", result), ran
    else:
        assert ran.status == "failed", ran
        assert error in (ran.error or ""), ran.error


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


@pytest.fixture
def new_default_pool(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A default pool that the test starts; it stops when the test ends."""
    monkeypatch.setattr(sandbox, "_pool", None)
    yield
    if sandbox._pool is not None:
        sandbox._pool.__exit__(None, None, None)


@pytest.mark.usefixtures("new_default_pool")
def test_each_program_runs_on_a_new_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    pids: list[int | None] = []
    segment = sandbox._segment

    def recorded(
        session: MontySession,
        run_state: sandbox._Run,
        begin: Callable[[], SyncSnapshot | ProgramStopped],
    ) -> ProgramWaiting | ProgramCompleted | ProgramStopped:
        pids.append(session.worker_pid)
        return segment(session, run_state, begin)

    monkeypatch.setattr(sandbox, "_segment", recorded)
    for _ in range(3):
        assert run("print(1)\n").stdout == "1\n"
    assert len(pids) == 3 and len(set(pids)) == 3, pids


@pytest.mark.usefixtures("new_default_pool")
def test_the_pool_runs_the_binary_of_its_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    decoy = tmp_path / "monty"
    decoy.write_text("#!/bin/sh\nexit 1\n")
    decoy.chmod(0o755)
    monkeypatch.setenv("MONTY_BIN", str(decoy))
    monkeypatch.setenv("PATH", str(tmp_path))
    assert run("print(1)\n").stdout == "1\n"


@pytest.mark.usefixtures("new_default_pool")
def test_the_pool_does_not_start_without_its_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sandbox.sysconfig, "get_path", lambda _name: str(tmp_path))
    with pytest.raises(FileNotFoundError, match="sandbox binary"):
        sandbox.sandbox_pool()


def _tenant_count(name: str, tenant_id: str) -> float:
    return _count(name, {"tenant_id": tenant_id})


def test_tenant_counters_follow_worker_time_and_busy_rejections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = "tenant_sandbox_metrics"
    monkeypatch.setattr(sandbox, "CHECKOUT_TIMEOUT_SECONDS", 0.5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
    try:
        seconds = _tenant_count(
            "onyx_code_mode_sandbox_worker_seconds_total", tenant_id
        )
        rejections = _tenant_count(
            "onyx_code_mode_sandbox_busy_rejections_total", tenant_id
        )
        with Monty(min_processes=1, max_processes=1, checkout_timeout=0.1) as pool:
            ran = run("print(await slow(seconds=0.5))\n", pool=pool)
            with pool.checkout():
                rejected = run("print(1)\n", pool=pool)
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
    assert ran.stdout == "done\n"
    assert rejected.error == BUSY_MESSAGE
    # The program kept its worker while its call ran: no other program waited.
    held = (
        _tenant_count("onyx_code_mode_sandbox_worker_seconds_total", tenant_id)
        - seconds
    )
    assert 0.5 <= held < 5, held
    assert (
        _tenant_count("onyx_code_mode_sandbox_busy_rejections_total", tenant_id)
        == rejections + 1
    )


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

    def counted(
        run: sandbox._Run, waiting: ProgramWaiting, worker: sandbox._Worker
    ) -> ProgramSuspended | None:
        dumps.append(1)
        return suspend(run, waiting, worker)

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
        clock=PausableClock(),
    )
    # A fake snapshot: skip the isinstance validation.
    waiting = ProgramWaiting.model_construct(state=cast(FunctionSnapshot, Snapshot()))
    monkeypatch.setattr(sandbox, "_worker_memory_bytes", lambda _pid: 0)
    worker = sandbox._Worker(pid=1, idle_bytes=0)
    assert sandbox._suspend(run_state, waiting, worker) is None
    assert sandbox._suspend(run_state, waiting, worker) is None
    # The second dump is skipped: the first did not fit.
    assert Snapshot.dumps == 1


def test_a_program_too_large_to_dump_keeps_its_worker(
    monkeypatch: pytest.MonkeyPatch, two_workers: Monty
) -> None:
    # Another program always waits, so each wait of this one gives up its worker.
    monkeypatch.setattr(sandbox._worker_demand, "gives_up", lambda _wake: True)
    over_memory = _suspensions("over_memory")
    # About 39 MB of heap: its dump would exceed the default memory limit.
    result = run(
        "big = 'x' * (39 * 1024 * 1024)\n"
        "store('k', 'v')\n"
        "print(await slow(seconds=0.1), len(big))\n",
        pool=two_workers,
    )
    assert (result.status, result.stdout) == (
        "completed",
        f"done {39 * 1024 * 1024}\n",
    ), result
    assert result.commits_store and result.store_writes == {"k": "v"}
    assert _suspensions("over_memory") == over_memory + 1


def test_the_worker_s_own_memory_does_not_count_toward_a_dump(
    monkeypatch: pytest.MonkeyPatch, two_workers: Monty
) -> None:
    monkeypatch.setattr(sandbox._worker_demand, "gives_up", lambda _wake: True)
    # A worker that holds the whole memory limit before the program runs.
    monkeypatch.setattr(
        sandbox, "_worker_memory_bytes", lambda _pid: LIMITS.max_memory_bytes
    )
    dumped = _suspensions("dumped")
    result = run("print(await slow(seconds=0.1))\n", pool=two_workers)
    assert (result.status, result.stdout) == ("completed", "done\n"), result
    assert _suspensions("dumped") == dumped + 1


def test_a_dump_that_runs_out_of_memory_fails_the_program_clearly(
    monkeypatch: pytest.MonkeyPatch, two_workers: Monty
) -> None:
    monkeypatch.setattr(sandbox._worker_demand, "gives_up", lambda _wake: True)
    # The worker's memory reads low, so the dump runs and exceeds the limit.
    monkeypatch.setattr(sandbox, "_worker_memory_bytes", lambda _pid: 0)
    lost = _worker_losses("out_of_memory")
    result = run(
        "big = 'x' * (39 * 1024 * 1024)\n"
        "store('k', 'v')\n"
        "print(await slow(seconds=0.1), len(big))\n",
        pool=two_workers,
    )
    assert (result.status, result.error) == ("failed", sandbox.DUMP_MEMORY_MESSAGE)
    assert not result.commits_store
    assert _worker_losses("out_of_memory") == lost + 1


def test_each_waiting_program_claims_one_holder() -> None:
    demand = sandbox._WorkerDemand(2)
    woken: list[str] = []
    first, second = _wakes(woken, "first", "second")
    waiters = _wakes([], "a", "b", "c")

    with demand.holding(first), demand.holding(second):
        with demand.waiting(waiters[0]):
            assert woken == ["first"]
            # A repeated claim adds none while the claim stands.
            demand.claim(waiters[0])
            assert woken == ["first"]
        # The waiter left before the holder gave up: the claim is withdrawn.
        assert not demand.gives_up(first)
        with demand.waiting(waiters[1]), demand.waiting(waiters[2]):
            assert woken == ["first", "first", "second"]
            assert demand.gives_up(first) and demand.gives_up(second)


def test_a_worker_freed_for_a_waiter_stands_in_for_its_claim() -> None:
    demand = sandbox._WorkerDemand(2)
    woken: list[str] = []
    first, second = _wakes(woken, "first", "second")
    waiter = partial(woken.append, "waiter")

    session = cast(MontySession, nullcontext())
    with ExitStack() as first_worker, demand.worker(session, second, "tenant"):
        first_worker.enter_context(demand.worker(session, first, "tenant"))
        with demand.holding(first), demand.holding(second), demand.waiting(waiter):
            assert woken == ["first"] and demand.gives_up(first)
            first_worker.close()
            # The waiter's checkout timed out as the first holder's worker
            # returned: that worker is free for its next checkout.
            demand.claim(waiter)
            assert woken == ["first"]
            # The next timeout means another program took the worker, so the
            # waiter claims again.
            demand.claim(waiter)
            assert woken == ["first", "second"]


class _ReturningSession:
    """A session whose worker return runs `on_return` first, as a checkout that
    another thread completes at that moment."""

    def __init__(self, on_return: Callable[[], None]) -> None:
        self._on_return = on_return

    def __enter__(self) -> "_ReturningSession":
        return self

    def __exit__(self, *_args: object) -> None:
        self._on_return()


def _wakes(woken: list[str], *names: str) -> list[Callable[[], None]]:
    return [partial(woken.append, name) for name in names]


def test_a_worker_taken_as_it_returns_leaves_no_credit_behind() -> None:
    demand = sandbox._WorkerDemand(2)
    woken: list[str] = []
    first, second, third = _wakes(woken, "first", "second", "third")
    waiter, late = _wakes([], "waiter", "late")
    with ExitStack() as stack:
        for holder in (first, second, third):
            stack.enter_context(demand.holding(holder))
        late_waiter = ExitStack()
        stack.enter_context(demand.waiting(waiter))
        late_waiter.enter_context(demand.waiting(late))
        assert woken == ["first", "second"]
        assert demand.gives_up(first) and demand.gives_up(second)

        def taken_by_the_late_waiter() -> None:
            stack.enter_context(
                demand.worker(cast(MontySession, nullcontext()), late, "tenant")
            )
            late_waiter.close()

        session = cast(MontySession, _ReturningSession(taken_by_the_late_waiter))
        with demand.worker(session, first, "tenant"):
            pass
        # The second holder's dump does not fit, so it keeps its worker.
        demand.kept(second)
        # The first holder's worker went to the late waiter, so the earlier
        # waiter claims the third holder.
        for _ in range(2):
            demand.claim(waiter)
        assert woken == ["first", "second", "third"]


def test_a_waiter_stopped_with_a_credit_leaves_no_credit_behind() -> None:
    demand = sandbox._WorkerDemand(2)
    woken: list[str] = []
    first, second, third = _wakes(woken, "first", "second", "third")
    stopped_waiter, waiter = _wakes([], "stopped", "waiter")
    with ExitStack() as stack:
        for holder in (first, second, third):
            stack.enter_context(demand.holding(holder))
        stopped = ExitStack()
        stopped.enter_context(demand.waiting(stopped_waiter))
        stack.enter_context(demand.waiting(waiter))
        assert demand.gives_up(first) and demand.gives_up(second)
        with demand.worker(cast(MontySession, nullcontext()), first, "tenant"):
            pass
        # The first waiter stops before it takes the worker freed for it.
        stopped.close()
        demand.kept(second)
        demand.claim(waiter)
        assert woken == ["first", "second", "third"]


def _slow_counted_dumps(monkeypatch: pytest.MonkeyPatch, seconds: float) -> list[int]:
    dumps: list[int] = []
    suspend = sandbox._suspend

    def slow_dump(
        run: sandbox._Run, waiting: ProgramWaiting, worker: sandbox._Worker
    ) -> ProgramSuspended | None:
        dumps.append(1)
        time.sleep(seconds)
        return suspend(run, waiting, worker)

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


@pytest.fixture
def always_dumped(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Each wait of a program gives up its worker, as under constant demand;
    returns the times at which a dumped program loads on a worker."""
    monkeypatch.setattr(sandbox._worker_demand, "gives_up", lambda _wake: True)
    loads: list[float] = []
    load = sandbox._load

    def counted(
        session: MontySession, run_state: sandbox._Run, suspended: ProgramSuspended
    ) -> SyncSnapshot:
        loads.append(time.monotonic())
        return load(session, run_state, suspended)

    monkeypatch.setattr(sandbox, "_load", counted)
    return loads


def test_a_dumped_program_resumes_for_a_batch_of_calls(
    always_dumped: list[float], two_workers: Monty
) -> None:
    calls = 20
    result = run(
        "out = await asyncio.gather("
        f"*[slow(seconds=0.2 + i * 0.02) for i in range({calls})])\n"
        "print(len(out))\n",
        limits=LIMITS.model_copy(update={"max_tool_calls": calls}),
        pool=two_workers,
    )
    assert (result.status, result.stdout) == ("completed", f"{calls}\n"), result
    # The calls end 20 ms apart; one load for each would be 20.
    assert 1 <= len(always_dumped) <= calls // 3, len(always_dumped)


def test_a_dumped_program_resumes_without_waiting_for_calls_it_does_not_await(
    always_dumped: list[float], two_workers: Monty
) -> None:
    printed: list[float] = []
    started = time.monotonic()
    result = run(
        "first = slow(seconds=3)\n"
        "second = slow(seconds=0.2)\n"
        "print(await second)\n"
        "print(await first)\n",
        on_stdout=lambda _text: printed.append(time.monotonic()),
        pool=two_workers,
    )
    assert (result.status, result.stdout) == ("completed", "done\ndone\n"), result
    assert always_dumped
    # The first line comes soon after the second call, not after the first.
    assert printed[0] - started < 1.5, printed[0] - started


@pytest.mark.usefixtures("always_dumped")
def test_yield_control_returns_at_once_while_a_dumped_program_waits(
    two_workers: Monty,
) -> None:
    yielded: list[float] = []
    started = time.monotonic()
    result = run(
        "print('before')\n"
        "yield_control()\n"
        "out = await asyncio.gather(slow(seconds=0.2), slow(seconds=1))\n"
        "print(len(out))\n",
        on_yield=lambda: yielded.append(time.monotonic()),
        pool=two_workers,
    )
    assert (result.status, result.stdout) == ("completed", "before\n2\n"), result
    assert yielded and yielded[0] - started < 0.5, yielded


def test_stop_ends_a_dumped_program_that_batches_its_calls(
    always_dumped: list[float], monkeypatch: pytest.MonkeyPatch, two_workers: Monty
) -> None:
    monkeypatch.setattr(sandbox, "RESUME_BATCH_SECONDS", 30.0)
    cancellation = CancellationSignal()
    # The first call ends at 0.2 s, then the batch window would last 30 s.
    threading.Timer(0.6, cancellation.cancel).start()
    started = time.monotonic()
    result = run(
        "out = await asyncio.gather(slow(seconds=0.2), slow(seconds=0.4), "
        "slow(seconds=1.5))\n",
        cancellation=cancellation,
        pool=two_workers,
    )
    assert result.status == "cancelled", result
    assert time.monotonic() - started < 1.5
    assert always_dumped == []


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
    release = threading.Event()

    def handler(_call: ExternalCall) -> object:
        release.wait(30)
        return "done"

    threading.Timer(0.3, cancellation.cancel).start()
    started = time.monotonic()
    result = run(
        "store('k', 1)\nawait slow(seconds=30)\n",
        handler,
        cancellation=cancellation,
        pool=two_workers,
    )
    # The call ignores cancellation; let it return so it frees its thread.
    release.set()
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
    holders: list[threading.Thread] = []
    with Monty(min_processes=1, max_processes=1, checkout_timeout=0.1) as pool:
        held = threading.Event()

        def hold_the_worker() -> None:
            # Waits for the worker as programs do, so the waiting program gives
            # it up.
            with sandbox._worker_demand.waiting(held.set):
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
            holder = threading.Thread(target=hold_the_worker)
            holders.append(holder)
            holder.start()
            assert held.wait(5)
            return "done"

        result = run("print(await slow(seconds=0))\n", handler, pool=pool)
        for holder in holders:
            holder.join(5)
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

    def probe() -> None:
        pass

    until(lambda: threads.acquire(probe))
    threads.release(probe)
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

    # The call returns its thread to the patched budget before the patch ends.
    def probe() -> None:
        pass

    until(lambda: threads.acquire(probe))
    threads.release(probe)


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
    for program in (first, first, first, second):
        threads.release(program)


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


def test_type_checker_notes_stay_within_the_output_limit() -> None:
    code = "".join(f"x{i}: int = 'a'\n" for i in range(60)) + "1 / 0\n"
    result = run(code)
    assert result.status == "failed"
    assert result.type_check_notes is not None
    # The last diagnostic is kept.
    assert "main.py:60:" in result.type_check_notes
    assert len(result.type_check_notes) < LIMITS.max_output_chars + 100


@pytest.mark.parametrize("paused", [True, False])
def test_a_call_that_pauses_the_clock_does_not_use_up_the_lifetime(
    paused: bool,
) -> None:
    clock = PausableClock()

    def wait_for_person(_call: ExternalCall) -> object:
        clock.set_paused(paused)
        time.sleep(1.5)
        clock.set_paused(False)
        return "done"

    result = execute_program(
        "print(await slow(seconds=0))\n",
        stubs=STUBS,
        function_names=FUNCTIONS,
        plain_functions={},
        async_functions={},
        handler=wait_for_person,
        limits=LIMITS.model_copy(update={"lifetime_seconds": 1}),
        cancellation=CancellationSignal(),
        on_print=lambda _text: None,
        on_yield=lambda: None,
        clock=clock,
    )

    assert result.status == ("completed" if paused else "timed_out"), result
