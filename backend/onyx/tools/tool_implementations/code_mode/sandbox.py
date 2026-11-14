"""Run model-written Python in a Monty sandbox; tool calls run on host threads."""

import atexit
import inspect
import math
import os
import re
import signal
import sysconfig
import threading
import time
from collections import deque
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import ExitStack, contextmanager, nullcontext
from functools import partial
from pathlib import Path
from typing import NamedTuple, NoReturn

import psutil
from pydantic_monty import (
    ExternalException,
    ExternalFuture,
    ExternalModule,
    ExternalResult,
    ExternalReturnValue,
    ExternalSettledResult,
    FunctionSnapshot,
    FutureSnapshot,
    Monty,
    MontyComplete,
    MontyCrashedError,
    MontyError,
    MontyRuntimeError,
    MontySession,
    MontySyntaxError,
    MontyTypingError,
    NameLookupSnapshot,
    OSPolicy,
    ResourceLimits,
    SyncSnapshot,
)

from onyx.llm.cancellation import CancellationSignal
from onyx.server.metrics import code_mode as metrics
from onyx.tools.tool_implementations.code_mode.models import (
    MAX_CPU_SECONDS,
    ExternalCall,
    PendingCall,
    ProgramCompleted,
    ProgramStopped,
    ProgramSuspended,
    ProgramWaiting,
    SandboxLimits,
    SandboxResult,
    SandboxStatus,
    TypeDiagnostic,
)
from onyx.tools.tool_implementations.code_mode.store import json_value
from onyx.tools.tool_implementations.utils import truncate_output, truncation_marker
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import call_later, start_thread_future
from onyx.utils.timing import PausableClock

logger = setup_logger()

# Seconds a new program waits for a free sandbox worker. A resumed program waits
# until its lifetime ends: its tool calls already ran.
CHECKOUT_TIMEOUT_SECONDS = 15.0
# The pool's own checkout timeout. A waiting program retries in steps of this
# length, so it notices Stop while it waits; the pool has no other wake-up.
CHECKOUT_POLL_SECONDS = 0.25
REQUEST_TIMEOUT_SECONDS = MAX_CPU_SECONDS + 15.0
# Sandbox worker processes per server process. A program that waits on its tools
# keeps its worker only while no other program waits for one, so 8 workers serve
# dozens of concurrent users. The bound keeps worst-case sandbox memory (workers x
# the per-program memory limit) near 1 GB, within the default API server pod
# limit. It is a constant because os.cpu_count() reports the node's CPUs, not the
# pod's limit.
MAX_SANDBOX_PROCESSES = 8
# Bytes of the dumped programs that the server process holds while they wait on
# their tools. A waiting program whose dump does not fit keeps its worker.
MAX_SUSPENDED_BYTES = 256 * 1024 * 1024
# A dump needs about the program's heap plus twice the dump size inside the
# worker, within `SandboxLimits.max_memory_bytes`, which budgets the program's
# allocations and not the worker's own memory. A waiting program whose worker
# grew by more than this share of that limit since checkout keeps its worker
# instead of dumping. With the default 128 MB limit, dumps run out of memory
# from about 34 MB of heap. In the first segment the growth also counts the type
# checker's memory, about 20 MB, so the check is stricter there. Monty type-checks
# and starts a program in one call, so no baseline can leave that memory out.
# Known gap: resident memory counts only the pages a program has written. A
# large allocation that the program never writes, such as `bytes(36_000_000)`,
# grows the worker by about 2 MB, so the check lets its dump run out of memory;
# the worker is then lost and the program fails with DUMP_MEMORY_MESSAGE. Monty
# reports no heap size. The check catches written data, such as tool results.
MAX_DUMP_MEMORY_SHARE = 1 / 4
# Callers (users and tenants) do not trust each other, so each worker serves one
# session and the pool then replaces it, as Monty's security model expects. A
# dumped program resumes on a new worker too.
MAX_CHECKOUTS_PER_WORKER = 1
MAX_RECURSION_DEPTH = 200
# A program suspends at each external call and each await on one, so the bound
# grows with the tool call limit; the base covers store(), load() and sleeps.
MAX_SUSPENSIONS_BASE = 1_000
MAX_SUSPENSIONS_PER_TOOL_CALL = 4
SCRIPT_NAME = "main.py"
CRASH_MESSAGE = (
    "The sandbox stopped unexpectedly. Values stored by earlier programs are kept; "
    "this program's writes are discarded. Earlier tool calls may have completed; "
    "check before you retry."
)
BUSY_MESSAGE = "The code sandbox is busy. Try again, or answer without code."
DUMP_MEMORY_MESSAGE = (
    "The sandbox ran out of memory while pausing this program to wait for its "
    "tool calls. This program's writes are discarded. Earlier tool calls may have "
    "completed; check before you retry. Keep less data in memory, for example by "
    "storing results with store() and keeping only what you need."
)
# Tool calls of one program that run at the same time, each on its own thread.
# Later calls wait in order for a free slot.
MAX_CONCURRENT_TOOL_CALLS = 16
# Cells whose program has not ended, in the server process
# (cells._RunningCells); each holds a driver thread. Programs give up their
# sandbox worker while they wait on tools, so most of these cells wait on
# tools, not on a worker.
MAX_RUNNING_CELLS = 64
# Threads of tool calls of all programs in the server process: a share of 3 for
# each running cell. Programs that want threads share them equally. A call that
# finds no thread within its program's share waits in its program's queue. A
# call that ignores cancellation keeps its thread until it returns.
MAX_TOOL_CALL_THREADS = MAX_RUNNING_CELLS * 3
# So at its limits a server process runs MAX_RUNNING_CELLS driver threads and
# MAX_TOOL_CALL_THREADS call threads for code mode, plus the threads of tools
# that run their own parallel work, such as a search that runs its queries in
# parallel.
# A call that returns this long after its program ended held its thread while
# ignoring cancellation; it is logged.
LATE_CALL_WARNING_SECONDS = 30.0
# A dumped program resumes on a new worker and loads its whole heap, so once one
# of its calls ends it waits this long for more of them, unless all end first.
# It is short against a tool call, so a program that awaits only some of its
# calls is barely delayed.
RESUME_BATCH_SECONDS = 0.1

YIELD_CONTROL_FUNCTION = "yield_control"
YIELD_CONTROL_STUB = '''def yield_control() -> None:
    """Return the output printed so far to the model now; the program keeps running."""
    ...'''
# A host function of one program, answered at once on the driver thread: a plain
# one such as store() returns its value, an async one returns it when
# awaited. Its signature binds the program's arguments; TypeError and
# ValueError are raised inside the program.
HostFunction = Callable[..., object]

# Standard library modules that every program has imported, as it has its tool
# functions; explicit imports of them also work. `os`, `sys` and `pathlib`
# import, but their file system, environment and process functions are denied.
IMPORTABLE_MODULES: tuple[str, ...] = (
    "asyncio",
    "base64",
    "collections",
    "csv",
    "dataclasses",
    "datetime",
    "decimal",
    "functools",
    "hashlib",
    "itertools",
    "json",
    "math",
    "os",
    "pathlib",
    "random",
    "re",
    "sys",
    "time",
    "typing",
)

# Fed without a type check before each new program in the same session, so the
# modules are globals while the program's line numbers stay its own.
_PRELUDE = f"import {', '.join(IMPORTABLE_MODULES)}"
# The same names for the type checker; each program's stubs include them.
PRELUDE_STUBS = "\n".join(f"import {name} as {name}" for name in IMPORTABLE_MODULES)
_SYNC_SLEEP = "system.sleep"
# The module that also holds every function of a program, so
# `from functions import f` and `functions.f(...)` work like the globals.
FUNCTIONS_MODULE = "functions"
# Global names the sandbox gives every program; tool functions must not shadow them.
SANDBOX_NAMES: frozenset[str] = frozenset(
    {*IMPORTABLE_MODULES, FUNCTIONS_MODULE, YIELD_CONTROL_FUNCTION}
)
# OS calls of an import: the type checker's stub request and the import itself.
# Monty answers them from the session's external modules.
_IMPORT_CALLS: frozenset[str] = frozenset({"import", "import_stubs"})
_ASYNC_SLEEP = "system.async_sleep"
# Monty's own message when a segment exceeds `max_feed_duration_secs`.
_COMPUTE_LIMIT_MESSAGE = re.compile(r"feed time limit exceeded: \S+ > \S+")

# Type errors on calls to tool functions are reliable: the stubs are exact. Other
# diagnostics are often false positives for valid Python (a name rebound to a value
# of another type), so they do not stop the program.
_FATAL_CALL_DIAGNOSTICS = frozenset(
    {
        "missing-argument",
        "unknown-argument",
        "invalid-argument-type",
        "too-many-positional-arguments",
        "parameter-already-assigned",
    }
)
_DIAGNOSTIC = re.compile(r"^\S+:\d+:\d+: error\[(?P<code>[\w-]+)\] (?P<message>.*)$")
_FUNCTION_IN_MESSAGE = re.compile(r"function `(?P<name>[\w.]+)`")


# Runs on a worker thread. The return value goes to the program; an Exception is
# raised inside the program.
ExternalCallHandler = Callable[[ExternalCall], object]


class StdoutCollector:
    """Collects printed text within a budget; the first `live_chars` are shown live.

    It keeps the first and the last half of `max_chars` characters and counts the
    ones in between, so a cut text always says how much it omitted.
    """

    def __init__(self, max_chars: int, live_chars: int) -> None:
        self._head_limit = max_chars // 2
        self._tail_limit = max_chars - self._head_limit
        self._live_limit = live_chars
        self._head: list[str] = []
        self._head_chars = 0
        self._tail: deque[str] = deque()
        self._tail_chars = 0
        self._dropped = 0
        self._live_chars = 0
        self._live_stopped = False

    def write(self, text: str) -> str:
        """Collect `text`; returns the part to show live."""
        live = self._live(text)
        head = text[: max(0, self._head_limit - self._head_chars)]
        if head:
            self._head.append(head)
            self._head_chars += len(head)
        rest = text[len(head) :]
        if rest:
            self._tail.append(rest)
            self._tail_chars += len(rest)
            self._trim_tail()
        return live

    def _trim_tail(self) -> None:
        excess = self._tail_chars - self._tail_limit
        while excess > 0:
            first = self._tail[0]
            if len(first) <= excess:
                self._tail.popleft()
                cut = len(first)
            else:
                self._tail[0] = first[excess:]
                cut = excess
            self._tail_chars -= cut
            self._dropped += cut
            excess -= cut

    def _live(self, text: str) -> str:
        if self._live_stopped:
            return ""
        remaining = self._live_limit - self._live_chars
        if len(text) > remaining:
            text = text[:remaining] + "\n... [further output is not shown live]\n"
            self._live_stopped = True
        self._live_chars += len(text)
        return text

    @property
    def dropped(self) -> int:
        """Characters the collector dropped from the middle."""
        return self._dropped

    @property
    def text(self) -> str:
        return self.cut(self._head_limit + self._tail_limit)

    def cut(self, max_chars: int) -> str:
        """The collected text within `max_chars`, cut in the middle; the marker
        counts every character omitted, also those the collector dropped."""
        head = "".join(self._head)
        tail = "".join(self._tail)
        if not self._dropped:
            # Nothing dropped: head and tail are one contiguous text.
            return truncate_output(
                head + tail, max_chars, label="code mode output", keep_tail=True
            )
        kept_head = min(max_chars // 2, len(head))
        kept_tail = min(max_chars - kept_head, len(tail))
        omitted = self._dropped + len(head) - kept_head + len(tail) - kept_tail
        return (
            head[:kept_head]
            + truncation_marker(omitted)
            + (tail[len(tail) - kept_tail :] if kept_tail else "")
        )


def parse_type_diagnostics(text: str) -> list[TypeDiagnostic]:
    """Parse ty's concise diagnostic lines."""
    diagnostics: list[TypeDiagnostic] = []
    for line in text.splitlines():
        match = _DIAGNOSTIC.match(line.strip())
        if match:
            diagnostics.append(
                TypeDiagnostic(
                    code=match.group("code"),
                    message=match.group("message"),
                    line=line.strip(),
                )
            )
    return diagnostics


def is_fatal_diagnostic(
    diagnostic: TypeDiagnostic, function_names: Collection[str]
) -> bool:
    if diagnostic.code == "invalid-syntax":
        return True
    if diagnostic.code not in _FATAL_CALL_DIAGNOSTICS:
        return False
    match = _FUNCTION_IN_MESSAGE.search(diagnostic.message)
    return match is not None and match.group("name") in function_names


_pool_lock = threading.Lock()
_pool: Monty | None = None


def sandbox_pool() -> Monty:
    """Process-wide pool of sandbox worker processes, started on first use."""
    global _pool
    with _pool_lock:
        if _pool is None:
            # Where pydantic-monty-runtime installs it: /usr/local/bin in the
            # Docker image, .venv/bin locally. MONTY_BIN and PATH never choose it.
            binary = Path(sysconfig.get_path("scripts")) / "monty"
            if not binary.is_file():
                raise FileNotFoundError(
                    f"The code mode sandbox binary {binary} is missing; install "
                    "pydantic-monty-runtime in this environment."
                )
            pool = Monty(
                binary_path=binary,
                min_processes=1,
                max_processes=MAX_SANDBOX_PROCESSES,
                checkout_timeout=CHECKOUT_POLL_SECONDS,
                request_timeout=REQUEST_TIMEOUT_SECONDS,
                max_checkouts_per_worker=MAX_CHECKOUTS_PER_WORKER,
            )
            pool.__enter__()
            atexit.register(pool.__exit__, None, None, None)
            _pool = pool
            metrics.set_code_mode_limits(
                sandbox_workers=MAX_SANDBOX_PROCESSES,
                suspended_bytes=MAX_SUSPENDED_BYTES,
                tool_call_threads=MAX_TOOL_CALL_THREADS,
                running_cells=MAX_RUNNING_CELLS,
            )
        return _pool


def _resource_limits(limits: SandboxLimits) -> ResourceLimits:
    return {
        "max_memory": limits.max_memory_bytes,
        "max_feed_duration_secs": limits.max_cpu_seconds,
        "max_recursion_depth": MAX_RECURSION_DEPTH,
        "max_suspensions": MAX_SUSPENSIONS_BASE
        + MAX_SUSPENSIONS_PER_TOOL_CALL * limits.max_tool_calls,
    }


_OS_POLICY: OSPolicy = {
    "datetime": "system",
    "timezone": "utc",
    "process_time": "zero",
    "random_start": "system",
    # The run's lifetime bounds sleeps; Monty's per-sleep cap would shorten them silently.
    "sleep_system_max": math.inf,
}


class _Aborted(Exception):
    def __init__(self, status: SandboxStatus, message: str) -> None:
        super().__init__(message)
        self.status: SandboxStatus = status


def _function_reference(name: str) -> Callable[..., NoReturn]:
    """A host function value for a tool name the program reads without calling."""

    def reference(*_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError("Tool functions run through sandbox snapshots")

    reference.__name__ = name
    reference.__qualname__ = name
    return reference


def _sandbox_exception(error: BaseException) -> Exception:
    # Monty maps builtin exception types; other classes lose their name.
    if type(error).__module__ == "builtins" and isinstance(error, Exception):
        return error
    return RuntimeError(str(error))


def _sleep_seconds(call: FunctionSnapshot) -> float:
    requested = call.args[0] if call.args else call.kwargs.get("seconds", 0)
    seconds = float(requested) if isinstance(requested, (int, float)) else 0.0
    # Also maps NaN to 0.
    return seconds if seconds > 0 else 0.0


def _is_compute_limit(error: MontyRuntimeError) -> bool:
    """Whether Monty stopped the program at its compute limit.

    Matches Monty's TimeoutError, whose message gives the measured and allowed
    durations, not other errors that mention a time limit.
    """
    return (
        isinstance(error.exception(), TimeoutError)
        and _COMPUTE_LIMIT_MESSAGE.fullmatch(error.display("msg")) is not None
    )


class _ToolCallThreads:
    """The process-wide budget of tool call threads (MAX_TOOL_CALL_THREADS).

    Programs are keyed by their wake-up callable. While several programs hold or
    wait for threads, each takes at most an equal share of the budget, so one
    program's calls cannot hold every thread while another program waits.
    """

    def __init__(self, limit: int) -> None:
        self._lock = threading.Lock()
        self._limit = limit
        self._in_use = 0
        self._held: dict[Callable[[], None], int] = {}
        # Wake-ups of programs whose queued calls wait for a thread.
        self._waiting: set[Callable[[], None]] = set()
        # Programs that ended while their calls still held threads: calls that
        # ignore cancellation, such as hung tools.
        self._ended: set[Callable[[], None]] = set()
        self._held_after_end = 0

    def acquire(self, wake: Callable[[], None]) -> bool:
        """Take a thread for the program of `wake`; when none is free within its
        share, call `wake` once one is released."""
        with self._lock:
            programs = len(self._held.keys() | self._waiting | {wake})
            share = max(1, self._limit // programs)
            held = self._held.get(wake, 0)
            if self._in_use < self._limit and held < share:
                self._in_use += 1
                metrics.TOOL_CALL_THREADS_IN_USE.set(self._in_use)
                self._held[wake] = held + 1
                self._waiting.discard(wake)
                return True
            self._waiting.add(wake)
            return False

    def release(self, wake: Callable[[], None]) -> None:
        with self._lock:
            self._in_use -= 1
            metrics.TOOL_CALL_THREADS_IN_USE.set(self._in_use)
            held = self._held.pop(wake) - 1
            if held:
                self._held[wake] = held
            if wake in self._ended:
                self._held_after_end -= 1
                metrics.TOOL_CALL_THREADS_HELD_AFTER_END.set(self._held_after_end)
                if not held:
                    self._ended.discard(wake)
            # Waiting programs keep their place in the share until they take a
            # thread or end (`end_program`).
            waiting = tuple(self._waiting)
        for program_wake in waiting:
            program_wake()

    def end_program(self, wake: Callable[[], None]) -> int:
        """The program of `wake` ended; returns the threads its calls still hold."""
        with self._lock:
            self._waiting.discard(wake)
            held = self._held.get(wake, 0)
            if held:
                self._ended.add(wake)
                self._held_after_end += held
                metrics.TOOL_CALL_THREADS_HELD_AFTER_END.set(self._held_after_end)
            return held


_tool_call_threads = _ToolCallThreads(MAX_TOOL_CALL_THREADS)


# A program's wake-up; it names the program as a holder and as a waiter.
_Wake = Callable[[], None]


class _WorkerDemand:
    """The sandbox workers this process has checked out, the programs that wait
    for one, and holders: programs that keep their worker while they wait on
    their tool calls.

    Each waiting program claims one holder, which gives up its worker; the other
    holders keep theirs. Before a claimed holder returns its worker, the claim
    becomes a credit of the waiter that made it, so the credit exists whenever
    that worker is free. A waiter with a claim or a credit claims no other
    holder. At the waiter's next checkout timeout the credit stands in for the
    claim, since the pool can still be replacing the worker, and is used up: if
    another program took the worker, the waiter claims again at the timeout
    after that. When a waiter stops waiting, its claim passes to the oldest
    waiter with neither a claim nor a credit. Without one, the claim is
    withdrawn from a holder that has not given up yet; a holder that has gives
    the credit to such a waiter when it returns its worker.
    """

    def __init__(self, workers: int) -> None:
        self._lock = threading.Lock()
        self._workers = workers
        self._busy = 0
        # Waiting programs, oldest first, and whether each has a credit.
        self._waiters: dict[_Wake, bool] = {}
        # Holders that keep their worker, oldest first.
        self._holders: dict[_Wake, None] = {}
        # Claimed holders, also those that gave up and still have the worker,
        # and the waiter each one frees a worker for; None when that waiter
        # stopped waiting and no other waiter needed the claim.
        self._claims: dict[_Wake, _Wake | None] = {}

    @property
    def all_busy(self) -> bool:
        with self._lock:
            return self._busy >= self._workers

    def _unserved(self) -> _Wake | None:
        """The oldest waiter with neither a claim nor a credit; the caller holds
        the lock."""
        served = set(self._claims.values())
        return next(
            (
                w
                for w, credit in self._waiters.items()
                if not credit and w not in served
            ),
            None,
        )

    def _pair(self) -> list[_Wake]:
        """Claim an unclaimed holder for each waiter with neither a claim nor a
        credit, oldest first; returns the holders to wake. The caller holds the
        lock and wakes them after it releases the lock."""
        served = set(self._claims.values())
        unclaimed = [h for h in self._holders if h not in self._claims]
        woken: list[_Wake] = []
        for waiter, credit in self._waiters.items():
            if len(woken) == len(unclaimed):
                break
            if credit or waiter in served:
                continue
            holder = unclaimed[len(woken)]
            self._claims[holder] = waiter
            woken.append(holder)
        return woken

    def _paired(self) -> None:
        with self._lock:
            woken = self._pair()
        for holder in woken:
            holder()

    @contextmanager
    def worker(
        self, session: MontySession, wake: _Wake, tenant_id: str
    ) -> Iterator[MontySession]:
        """Check out the session's worker; raises TimeoutError when none is free.

        A claim on the program becomes its waiter's credit before the worker is
        back in the pool; the time it held the worker counts for its tenant.
        """
        with session:
            with self._lock:
                self._busy += 1
            checked_out = time.monotonic()
            try:
                yield session
            finally:
                with self._lock:
                    self._busy -= 1
                    if wake in self._claims:
                        waiter = self._claims.pop(wake)
                        if waiter is None:
                            waiter = self._unserved()
                        if waiter is not None:
                            self._waiters[waiter] = True
                metrics.SANDBOX_WORKER_SECONDS.labels(tenant_id=tenant_id).inc(
                    time.monotonic() - checked_out
                )

    @contextmanager
    def waiting(self, wake: _Wake) -> Iterator[None]:
        with self._lock:
            self._waiters[wake] = False
        self._paired()
        try:
            yield
        finally:
            with self._lock:
                del self._waiters[wake]
                claimed = next((h for h, w in self._claims.items() if w == wake), None)
                if claimed is not None:
                    heir = self._unserved()
                    if heir is not None:
                        self._claims[claimed] = heir
                    elif claimed in self._holders:
                        del self._claims[claimed]
                    else:
                        self._claims[claimed] = None

    def claim(self, wake: _Wake) -> None:
        """At a checkout timeout of the waiter `wake`: use up its credit, or
        claim a holder for it when it has neither a credit nor a claim."""
        with self._lock:
            if self._waiters.get(wake):
                self._waiters[wake] = False
                return
        self._paired()

    def gives_up(self, wake: _Wake) -> bool:
        """Whether the holder of `wake` is claimed. A claimed holder stops
        holding; its claim counts until it returns or keeps its worker."""
        with self._lock:
            if wake not in self._claims:
                return False
            self._holders.pop(wake, None)
            return True

    def kept(self, wake: _Wake) -> None:
        """The program that gave up its worker keeps it: its dump does not fit.
        Its waiter claims another holder."""
        with self._lock:
            self._claims.pop(wake, None)
        self._paired()

    @contextmanager
    def holding(self, wake: _Wake) -> Iterator[None]:
        with self._lock:
            self._holders[wake] = None
        self._paired()
        try:
            yield
        finally:
            with self._lock:
                # A holder that did not give up drops a claim it had not seen;
                # its waiter claims another holder.
                dropped = wake in self._holders
                if dropped:
                    del self._holders[wake]
                    self._claims.pop(wake, None)
            if dropped:
                self._paired()


class _SuspendedBytes:
    """The budget of dumped programs held in the server process
    (MAX_SUSPENDED_BYTES)."""

    def __init__(self, limit: int) -> None:
        self._lock = threading.Lock()
        self._free = limit

    @property
    def free(self) -> int:
        with self._lock:
            return self._free

    def reserve(self, size: int) -> bool:
        with self._lock:
            if size > self._free:
                return False
            self._free -= size
            metrics.SUSPENDED_BYTES.inc(size)
            return True

    def release(self, size: int) -> None:
        with self._lock:
            self._free += size
            metrics.SUSPENDED_BYTES.dec(size)


_worker_demand = _WorkerDemand(MAX_SANDBOX_PROCESSES)
_suspended_bytes = _SuspendedBytes(MAX_SUSPENDED_BYTES)


def _call_host(
    name: str,
    function: HostFunction,
    signature: inspect.Signature,
    call: FunctionSnapshot,
) -> ExternalReturnValue | ExternalException:
    try:
        signature.bind(*call.args, **call.kwargs)
    except TypeError as error:
        return ExternalException(exception=TypeError(f"{name}(): {error}"))
    try:
        return ExternalReturnValue(return_value=function(*call.args, **call.kwargs))
    except (TypeError, ValueError) as error:
        return ExternalException(exception=error)


class _Run:
    """State of one execution: pending tool calls, limits and output."""

    def __init__(
        self,
        *,
        limits: SandboxLimits,
        function_names: Collection[str],
        plain_functions: Mapping[str, HostFunction],
        async_functions: Mapping[str, HostFunction],
        handler: ExternalCallHandler,
        cancellation: CancellationSignal,
        on_print: Callable[[str], None],
        on_yield: Callable[[], None],
        on_blocked: Callable[[bool, Callable[[], None]], bool],
        clock: PausableClock,
    ) -> None:
        self.limits = limits
        self.function_names = frozenset(function_names)
        self.tenant_id = metrics.current_tenant_id()

        def yield_control() -> None:
            on_yield()

        functions: dict[str, HostFunction] = {
            **plain_functions,
            YIELD_CONTROL_FUNCTION: yield_control,
        }
        self.plain_functions = {
            name: (function, inspect.signature(function))
            for name, function in functions.items()
        }
        self.async_functions = {
            name: (function, inspect.signature(function))
            for name, function in async_functions.items()
        }
        # Results of async host function calls, until the program awaits them.
        self.host_results: dict[int, ExternalSettledResult] = {}
        # Every name a program can call; the type checker stops calls to these
        # with wrong arguments.
        self.callable_names = (
            self.function_names | frozenset(functions) | frozenset(async_functions)
        )
        self.handler = handler
        self.cancellation = cancellation

        def print_callback(_stream: str, text: str) -> None:
            on_print(text)

        self.print_callback = print_callback
        self.on_blocked = on_blocked
        # The program waits for tool calls only, as last reported to `on_blocked`.
        self.blocked = False
        # The clock starts when the first worker is checked out, so time spent
        # queueing for a worker does not count.
        self.started: float | None = None
        # The end of the lifetime on `clock`, which stands still while the
        # caller pauses it, for example while a call waits for the user.
        self.clock = clock
        self.deadline = math.inf
        # When the program ended; its calls that still run hold their threads.
        self.ended: float | None = None
        # Unfinished tool calls by sandbox call id, in call order.
        self.calls: dict[int, PendingCall] = {}
        # Unfinished sleeps by sandbox call id: the monotonic time each one ends.
        self.sleeps: dict[int, float] = {}
        # Set when a call ends, a tool call thread frees up, or the run is cancelled.
        self.wake = threading.Event()
        self.tool_calls = 0
        # Bytes of the program's last dump; a dump this large that cannot fit is
        # not attempted.
        self.last_dump_bytes = 0
        # Non-fatal type checker diagnostics of the program.
        self.type_check_notes: str | None = None

    def start_clock(self) -> None:
        if self.started is None:
            self.started = time.monotonic()
            self.deadline = self.clock.now() + self.limits.lifetime_seconds

    def abort_reason(self) -> "_Aborted | None":
        if self.cancellation.cancelled:
            return _Aborted("cancelled", "The execution was cancelled.")
        if self.clock.now() >= self.deadline:
            return _Aborted(
                "timed_out",
                f"TimeoutError: the program did not finish within "
                f"{self.limits.lifetime_seconds:g} seconds (wall clock, including "
                "tool calls).",
            )
        return None

    def check(self) -> None:
        aborted = self.abort_reason()
        if aborted is not None:
            raise aborted

    def drive(
        self, state: SyncSnapshot
    ) -> MontyComplete | FutureSnapshot | FunctionSnapshot:
        """Run until the program completes or waits.

        It waits at a FutureSnapshot whose calls and sleeps are all unfinished, or
        at a FunctionSnapshot of a synchronous sleep that has not ended.
        """
        while not isinstance(state, MontyComplete):
            self.check()
            if isinstance(state, NameLookupSnapshot):
                name = state.variable_name
                state = (
                    state.resume(value=_function_reference(name))
                    if name in self.callable_names
                    else state.resume()
                )
            elif isinstance(state, FunctionSnapshot):
                if state.is_os_function and state.function_name in _IMPORT_CALLS:
                    state = state.resume_auto()
                elif state.is_os_function and state.function_name == _SYNC_SLEEP:
                    # A resumed program announces the same sleep call again.
                    self.sleeps.setdefault(
                        state.call_id, time.monotonic() + _sleep_seconds(state)
                    )
                    if not self._finished(state.call_id):
                        return state
                    del self.sleeps[state.call_id]
                    state = state.resume(ExternalReturnValue(return_value=None))
                else:
                    state = state.resume(self._answer_call(state))
            elif isinstance(state, FutureSnapshot):
                settled = self.settled(state.pending_call_ids)
                if not settled:
                    return state
                state = state.resume(settled)
        return state

    def _answer_call(self, call: FunctionSnapshot) -> ExternalResult:
        name = call.function_name
        if call.is_os_function:
            if name == _ASYNC_SLEEP:
                self.sleeps[call.call_id] = time.monotonic() + _sleep_seconds(call)
                return ExternalFuture(future=...)
            return ExternalException(
                exception=PermissionError(
                    f"{name} is not available in this sandbox; use the tool functions."
                )
            )
        # A call through the module, such as `functions.f(...)`, is a call of `f`.
        name = name.removeprefix(f"{FUNCTIONS_MODULE}.")
        if name in self.plain_functions:
            return _call_host(name, *self.plain_functions[name], call)
        if name in self.async_functions:
            self.host_results[call.call_id] = _call_host(
                name, *self.async_functions[name], call
            )
            return ExternalFuture(future=...)
        if name not in self.function_names:
            return ExternalException(
                exception=NameError(f"name '{name}' is not defined")
            )
        if call.args:
            return ExternalException(
                exception=TypeError(
                    f"{name}() takes keyword arguments only, for example "
                    f"{name}(argument=value)"
                )
            )
        if self.tool_calls >= self.limits.max_tool_calls:
            return ExternalException(
                exception=RuntimeError(
                    f"Tool call limit reached: at most {self.limits.max_tool_calls} "
                    "tool calls per execution."
                )
            )
        self.calls[call.call_id] = PendingCall(
            external=ExternalCall(
                index=self.tool_calls, function_name=name, kwargs=dict(call.kwargs)
            )
        )
        self.tool_calls += 1
        self.start_queued()
        return ExternalFuture(future=...)

    def start_queued(self) -> None:
        """Start queued calls, in call order, while fewer than
        MAX_CONCURRENT_TOOL_CALLS run and the process has a free call thread."""
        running = sum(
            1
            for pending in self.calls.values()
            if pending.future is not None and not pending.future.done()
        )
        for pending in self.calls.values():
            if pending.future is not None:
                continue
            if running >= MAX_CONCURRENT_TOOL_CALLS or not _tool_call_threads.acquire(
                self.wake.set
            ):
                return
            try:
                pending.future = start_thread_future(
                    partial(self._call_thread, pending.external),
                    name=f"code-mode-{pending.external.function_name}",
                )
            except BaseException:
                _tool_call_threads.release(self.wake.set)
                raise
            pending.future.add_done_callback(lambda _future: self.wake.set())
            running += 1

    def _call_thread(self, external: ExternalCall) -> object:
        try:
            return self.handler(external)
        finally:
            _tool_call_threads.release(self.wake.set)
            ended = self.ended
            if (
                ended is not None
                and (late := time.monotonic() - ended) >= LATE_CALL_WARNING_SECONDS
            ):
                logger.warning(
                    "Code mode tool call %s returned %.0f s after its program ended",
                    external.function_name,
                    late,
                )

    def running_call_names(self) -> list[str]:
        return [
            pending.external.function_name
            for pending in self.calls.values()
            if pending.future is not None and not pending.future.done()
        ]

    def _finished(self, call_id: int) -> bool:
        """Whether a call or sleep has ended; an unknown id counts as ended."""
        if call_id in self.sleeps:
            return self.sleeps[call_id] <= time.monotonic()
        if call_id in self.host_results:
            return True
        pending = self.calls.get(call_id)
        return pending is None or (pending.future is not None and pending.future.done())

    def wait_for_any(
        self,
        call_ids: list[int],
        *,
        yield_worker: bool = False,
        batch_seconds: float = 0.0,
    ) -> bool:
        """Wait until one of the calls or sleeps ends; True once one has.

        With `yield_worker`, the program keeps its worker while it waits and
        returns False as soon as another program waits for a worker. With
        `batch_seconds`, it then waits that long for the others, unless all of
        them end first.
        """
        batch_end = math.inf
        with _worker_demand.holding(self.wake.set) if yield_worker else nullcontext():
            while True:
                # Cleared before the checks, so a wake-up during them is not lost.
                self.wake.clear()
                self.check()
                self.start_queued()
                pending = [i for i in call_ids if not self._finished(i)]
                now = time.monotonic()
                ended = False
                if len(pending) < len(call_ids):
                    batch_end = min(batch_end, now + batch_seconds)
                    ended = not pending or now >= batch_end
                if ended:
                    # A program that waited for tool calls only continues once
                    # the caller lets it; until then it waits here, where it
                    # can give up its worker.
                    if not self.blocked or self.on_blocked(False, self.wake.set):
                        self.blocked = False
                        return True
                elif (
                    pending
                    and not self.blocked
                    and all(i in self.calls for i in pending)
                ):
                    # Tool calls alone can wake the program, not a sleep's end.
                    self.blocked = True
                    self.on_blocked(True, self.wake.set)
                if yield_worker and _worker_demand.gives_up(self.wake.set):
                    return False
                # A sleep's end sets no event.
                wakeup = min(
                    (self.sleeps[i] for i in pending if i in self.sleeps),
                    default=math.inf,
                )
                timeout = min(
                    wakeup - now,
                    math.inf if ended else batch_end - now,
                    self.deadline - self.clock.now(),
                )
                self.wake.wait(None if math.isinf(timeout) else max(0.0, timeout))

    def settled(self, call_ids: list[int]) -> dict[int, ExternalSettledResult]:
        """Results of the calls and sleeps that ended; takes them out of the run."""
        unknown: dict[int, ExternalSettledResult] = {
            call_id: ExternalException(
                exception=RuntimeError("Unknown pending call in the sandbox")
            )
            for call_id in call_ids
            if call_id not in self.calls
            and call_id not in self.sleeps
            and call_id not in self.host_results
        }
        if unknown:
            return unknown
        results: dict[int, ExternalSettledResult] = {}
        for call_id in call_ids:
            if not self._finished(call_id):
                continue
            if call_id in self.sleeps:
                del self.sleeps[call_id]
                results[call_id] = ExternalReturnValue(return_value=None)
                continue
            if call_id in self.host_results:
                results[call_id] = self.host_results.pop(call_id)
                continue
            future = self.calls.pop(call_id).future
            if future is None:
                continue
            error = future.exception()
            if error is None:
                results[call_id] = ExternalReturnValue(return_value=future.result())
            elif isinstance(error, Exception):
                results[call_id] = ExternalException(
                    exception=_sandbox_exception(error)
                )
            else:
                # Cancellation and other control flow end the execution.
                raise error
        return results

    def unawaited_calls(self) -> tuple[ExternalCall, ...]:
        """Tool calls the program started and never awaited that have not finished."""
        return tuple(
            pending.external
            for pending in self.calls.values()
            if pending.future is not None and not pending.future.done()
        )

    def unstarted_calls(self) -> tuple[ExternalCall, ...]:
        """Tool calls the program never awaited that are still queued."""
        return tuple(
            pending.external
            for pending in self.calls.values()
            if pending.future is None
        )

    @property
    def elapsed(self) -> float:
        return 0.0 if self.started is None else time.monotonic() - self.started


def _kill_worker(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


@contextmanager
def _watched(run: _Run, pid: int | None) -> Iterator[None]:
    """Kill the worker if the run is cancelled, or reaches its deadline, while the
    program computes on it.

    The driver checks the run only between snapshots, so a busy loop would
    otherwise ignore Stop and the wall clock until the compute limit. A timer runs
    only when the deadline can fall within the segment's compute limit, and
    rechecks the run's clock when it fires. The pool replaces a killed worker.
    """
    lock = threading.Lock()
    computing = pid
    cancel_timer: Callable[[], None] | None = None

    def kill() -> None:
        nonlocal computing
        with lock:
            if computing is not None:
                _kill_worker(computing)
                metrics.count_worker_lost("killed")
                computing = None

    def kill_at_deadline() -> None:
        nonlocal cancel_timer
        # The clock stands still while the run's calls wait.
        remaining = run.deadline - run.clock.now()
        if remaining <= 0:
            kill()
            return
        with lock:
            if computing is not None:
                cancel_timer = call_later(remaining, kill_at_deadline)

    remaining = run.deadline - run.clock.now()
    if remaining < run.limits.max_cpu_seconds:
        cancel_timer = call_later(max(0.0, remaining), kill_at_deadline)
    try:
        with run.cancellation.on_cancel(kill):
            yield
    finally:
        # Under the lock, so the worker is never killed after it is returned,
        # and no timer starts after this one is cancelled.
        with lock:
            computing = None
            if cancel_timer is not None:
                cancel_timer()


def _start(
    session: MontySession, code: str, run: _Run
) -> SyncSnapshot | ProgramStopped:
    """Import the allowed modules, then type-check and start the program.

    Invalid syntax and type errors in calls stop it; other diagnostics become
    notes.
    """
    with metrics.PROGRAM_START_DURATION.time():
        session.feed_run(_PRELUDE, skip_type_check=True)
        try:
            return session.feed_start(code, print_callback=run.print_callback)
        except MontyTypingError as error:
            diagnostics = parse_type_diagnostics(error.display())
            text = "\n".join(d.line for d in diagnostics) or error.display()
            if any(is_fatal_diagnostic(d, run.callable_names) for d in diagnostics):
                return ProgramStopped(
                    status="failed",
                    error="Type check failed; the program did not run.\n" + text,
                )
            run.type_check_notes = text
            return session.feed_start(
                code, print_callback=run.print_callback, skip_type_check=True
            )


def _load(
    session: MontySession, run: _Run, suspended: ProgramSuspended
) -> SyncSnapshot:
    try:
        return session.load_snapshot(
            suspended.snapshot, print_callback=run.print_callback
        )
    finally:
        _suspended_bytes.release(len(suspended.snapshot))


def _segment(
    session: MontySession,
    run: _Run,
    begin: Callable[[], SyncSnapshot | ProgramStopped],
) -> ProgramWaiting | ProgramCompleted | ProgramStopped:
    """Run the program on its worker from `begin` until it completes, fails or
    waits."""
    try:
        with _watched(run, session.worker_pid):
            state = begin()
            if isinstance(state, ProgramStopped):
                return state
            outcome = run.drive(state)
    except MontySyntaxError as error:
        return ProgramStopped(status="failed", error=error.display())
    except MontyRuntimeError as error:
        if _is_compute_limit(error):
            return ProgramStopped(status="timed_out", error=error.display())
        return ProgramStopped(status="failed", error=error.display(), raised=True)
    if isinstance(outcome, MontyComplete):
        return ProgramCompleted(output=outcome.output)
    return ProgramWaiting(state=outcome)


def _resumed(waiting: ProgramWaiting) -> SyncSnapshot:
    return waiting.state


def _worker_memory_bytes(pid: int | None) -> int | None:
    """Resident memory of a sandbox worker; None when it cannot be read."""
    if pid is None:
        return None
    try:
        return psutil.Process(pid).memory_info().rss
    except psutil.Error:
        return None


class _Worker(NamedTuple):
    """A checked-out worker and its resident memory before the program ran."""

    pid: int | None
    idle_bytes: int | None

    def memory_growth(self) -> int | None:
        """Bytes the worker grew by since checkout; None when unknown."""
        memory = _worker_memory_bytes(self.pid)
        if memory is None or self.idle_bytes is None:
            return None
        return memory - self.idle_bytes


def _checked_out(session: MontySession) -> _Worker:
    return _Worker(session.worker_pid, _worker_memory_bytes(session.worker_pid))


def _suspend(
    run: _Run, waiting: ProgramWaiting, worker: _Worker
) -> ProgramSuspended | None:
    """Dump a waiting program; None when it keeps its worker instead.

    It keeps its worker when its dump does not fit MAX_SUSPENDED_BYTES, or when
    the worker grew too much since checkout to dump (MAX_DUMP_MEMORY_SHARE), or
    its memory cannot be read. The program's last dump size estimates the next,
    so a dump that cannot fit is skipped. Raises `_Aborted` when the dump still
    runs out of memory: the worker is gone, so the program cannot continue.
    """
    if run.last_dump_bytes > _suspended_bytes.free:
        metrics.count_suspension("over_budget")
        return None
    growth = worker.memory_growth()
    if growth is None or growth > run.limits.max_memory_bytes * MAX_DUMP_MEMORY_SHARE:
        metrics.count_suspension("over_memory")
        return None
    try:
        snapshot = waiting.state.dump()
    except MontyRuntimeError as error:
        if not isinstance(error.exception(), MemoryError):
            raise
        logger.warning("Code mode sandbox worker ran out of memory in a dump")
        metrics.count_worker_lost("out_of_memory")
        raise _Aborted("failed", DUMP_MEMORY_MESSAGE) from error
    run.last_dump_bytes = len(snapshot)
    if not _suspended_bytes.reserve(len(snapshot)):
        metrics.count_suspension("over_budget")
        return None
    metrics.count_suspension("dumped")
    return ProgramSuspended(snapshot=snapshot, call_ids=waiting.call_ids)


def _functions_module(run: _Run, stubs: str) -> ExternalModule:
    """The `functions` module: every function of the program, typed by its stubs.

    The pool builds it only in a session whose program imports it.
    """
    return ExternalModule(
        {name: _function_reference(name) for name in run.callable_names},
        stubs=stubs,
    )


@contextmanager
def _checkout(
    pool: Monty,
    run: _Run,
    *,
    resumed: bool,
    stubs: str,
    limits: ResourceLimits,
    functions: Callable[[], ExternalModule],
) -> Iterator[MontySession]:
    """Check out a worker; stop waiting once the run is cancelled or late.

    Raises `_Aborted` when the run stops. A new program raises TimeoutError when
    no worker is free within CHECKOUT_TIMEOUT_SECONDS; a resumed one waits until
    its lifetime ends. It waits at once when every worker is checked out. While
    it waits, programs that keep a worker give theirs up.
    """
    give_up = math.inf if resumed else time.monotonic() + CHECKOUT_TIMEOUT_SECONDS
    with ExitStack() as stack:
        with ExitStack() as demand:
            waiting = False

            def wait() -> None:
                nonlocal waiting
                demand.enter_context(_worker_demand.waiting(run.wake.set))
                demand.enter_context(
                    metrics.PROGRAMS_WAITING_FOR_WORKER.track_inprogress()
                )
                waiting = True

            while True:
                run.check()
                if not waiting and _worker_demand.all_busy:
                    wait()
                session = pool.checkout(
                    script_name=SCRIPT_NAME,
                    limits=limits,
                    type_check=not resumed,
                    type_check_stubs=None if resumed else stubs,
                    type_check_format="concise",
                    os_policy=_OS_POLICY,
                    external_modules={FUNCTIONS_MODULE: functions},
                )
                try:
                    stack.enter_context(
                        _worker_demand.worker(session, run.wake.set, run.tenant_id)
                    )
                    stack.enter_context(metrics.SANDBOX_WORKERS_BUSY.track_inprogress())
                    break
                except TimeoutError:
                    if time.monotonic() >= give_up:
                        raise
                    if waiting:
                        _worker_demand.claim(run.wake.set)
                    else:
                        wait()
        yield session


def execute_program(
    code: str,
    *,
    stubs: str,
    function_names: Collection[str],
    plain_functions: Mapping[str, HostFunction],
    async_functions: Mapping[str, HostFunction],
    handler: ExternalCallHandler,
    cancellation: CancellationSignal,
    limits: SandboxLimits,
    on_print: Callable[[str], None],
    on_yield: Callable[[], None],
    on_blocked: Callable[[bool, Callable[[], None]], bool],
    clock: PausableClock,
    pool: Callable[[], Monty] = sandbox_pool,
) -> SandboxResult:
    """Run one program in a fresh interpreter. Raises the handler's BaseException.

    `stubs` types the program's functions and includes PRELUDE_STUBS.
    `cancellation` stops the program at once, also while it computes or waits.
    `on_print` receives the printed text and `on_yield` each yield_control() call,
    both on the driver thread. `on_blocked(True, wake)`, also on the driver
    thread, reports that the program starts to wait for unfinished tool calls
    only. Before it continues, `on_blocked(False, wake)` returns whether it
    may. When it may not, the caller calls `wake` once it may, and the program
    keeps waiting and can give up its worker. The program's lifetime runs on
    `clock`. Nothing carries
    over from earlier programs; plain functions such as load() give a program
    outside state.
    The program waits at each await on unfinished tool calls or sleeps, and at
    each synchronous sleep. It keeps its worker while it waits, until another
    program waits for one; then it is dumped, its worker returned to the pool, and
    it resumes on a new worker once its calls and sleeps end, or
    RESUME_BATCH_SECONDS after the first of them ends. When the program
    ends, calls it never awaited are not waited for, and queued calls never start;
    the caller cancels the running ones.
    """
    run = _Run(
        limits=limits,
        function_names=function_names,
        plain_functions=plain_functions,
        async_functions=async_functions,
        handler=handler,
        cancellation=cancellation,
        on_print=on_print,
        on_yield=on_yield,
        on_blocked=on_blocked,
        clock=clock,
    )

    def bounded(text: str | None, label: str) -> str | None:
        if text is None:
            return None
        return truncate_output(text, limits.max_output_chars, label, keep_tail=True)

    def finish(
        status: SandboxStatus,
        *,
        result: str | None = None,
        error: str | None = None,
        raised: bool = False,
    ) -> SandboxResult:
        return SandboxResult(
            status=status,
            result=bounded(result, "code mode result"),
            error=bounded(error, "code mode error"),
            duration_seconds=run.elapsed,
            type_check_notes=None
            if status == "completed"
            else bounded(run.type_check_notes, "type checker notes"),
            # A stop can surface as an exception that the program raises.
            commits_store=status == "completed"
            or (raised and run.abort_reason() is None),
            unawaited_calls=run.unawaited_calls() if status == "completed" else (),
            unstarted_calls=run.unstarted_calls() if status == "completed" else (),
        )

    resource_limits = _resource_limits(limits)
    functions = partial(_functions_module, run, stubs)
    # A dumped program that waits for its calls without a worker.
    suspended: ProgramSuspended | None = None
    try:
        with cancellation.on_cancel(run.wake.set):
            while True:
                with _checkout(
                    pool(),
                    run,
                    resumed=suspended is not None,
                    stubs=stubs,
                    limits=resource_limits,
                    functions=functions,
                ) as session:
                    run.start_clock()
                    worker = _checked_out(session)
                    loading, suspended = suspended, None
                    step = _segment(
                        session,
                        run,
                        partial(_start, session, code, run)
                        if loading is None
                        else partial(_load, session, run, loading),
                    )
                    while isinstance(step, ProgramWaiting):
                        if not run.wait_for_any(step.call_ids, yield_worker=True):
                            suspended = _suspend(run, step, worker)
                            if suspended is not None:
                                break
                            _worker_demand.kept(run.wake.set)
                            run.wait_for_any(step.call_ids)
                        step = _segment(session, run, partial(_resumed, step))
                if not isinstance(step, ProgramWaiting):
                    ended = step
                    break
                if suspended is not None:
                    run.wait_for_any(
                        suspended.call_ids, batch_seconds=RESUME_BATCH_SECONDS
                    )
        if isinstance(ended, ProgramStopped):
            return finish(ended.status, error=ended.error, raised=ended.raised)
    except _Aborted as aborted:
        return finish(aborted.status, error=str(aborted))
    except MontyCrashedError as error:
        # `_watched` kills the worker on cancellation and at the deadline.
        aborted = run.abort_reason()
        if aborted is not None:
            return finish(aborted.status, error=str(aborted))
        logger.warning("Code mode sandbox worker crashed: %s", error)
        metrics.count_worker_lost("crashed")
        return finish("timed_out" if error.timed_out else "failed", error=CRASH_MESSAGE)
    except MontyError as error:
        logger.warning("Code mode sandbox failed: %s", error)
        return finish("failed", error=f"{type(error).__name__}: {error}")
    except TimeoutError:
        metrics.SANDBOX_BUSY_REJECTIONS.labels(tenant_id=run.tenant_id).inc()
        return finish("failed", error=BUSY_MESSAGE)
    finally:
        run.ended = time.monotonic()
        if _tool_call_threads.end_program(run.wake.set):
            logger.info(
                "Code mode program ended with tool calls still running: %s",
                ", ".join(run.running_call_names()),
            )
        if suspended is not None:
            _suspended_bytes.release(len(suspended.snapshot))
    if ended.output is None:
        return finish("completed")
    try:
        output = json_value(
            ended.output, "The value of the last expression", limits.max_result_bytes
        ).value
    except (TypeError, ValueError) as error:
        return finish("completed", error=str(error))
    return finish("completed", result=repr(output))
