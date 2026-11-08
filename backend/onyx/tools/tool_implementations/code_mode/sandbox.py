"""Run model-written Python in a Monty sandbox; tool calls run on host threads."""

import atexit
import inspect
import math
import os
import re
import signal
import threading
import time
from collections import deque
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import ExitStack, contextmanager, nullcontext
from functools import partial
from typing import NoReturn

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
# Checkouts after which a worker is replaced; a worker that hit the memory limit
# keeps its high-water memory until then.
MAX_CHECKOUTS_PER_WORKER = 50
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
# Tool calls of one program that run at the same time, each on its own thread.
# Later calls wait in order for a free slot.
MAX_CONCURRENT_TOOL_CALLS = 16
# Threads of tool calls of all programs in the server process. Programs that
# want threads share them equally. A call that finds no thread within its
# program's share waits in its program's queue. A call that ignores cancellation
# keeps its thread until it returns. A tool that runs its own parallel work, such
# as a search that runs its queries in parallel, adds its threads to its call's.
MAX_TOOL_CALL_THREADS = 192
# A call that returns this long after its program ended held its thread while
# ignoring cancellation; it is logged.
LATE_CALL_WARNING_SECONDS = 30.0

YIELD_CONTROL_FUNCTION = "yield_control"
YIELD_CONTROL_STUB = '''def yield_control() -> None:
    """Return the output printed so far to the model now; the program keeps running."""
    ...'''
# A host function of one program, answered at once on the driver thread: a plain
# one such as store() returns its value, an async one returns it when
# awaited. Its signature binds the program's arguments; TypeError and
# ValueError are raised inside the program.
HostFunction = Callable[..., object]

# Standard library modules that programs can import. `os`, `sys` and `pathlib`
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

_SYNC_SLEEP = "system.sleep"
# The module that also holds every function of a program, so
# `from functions import f` and `functions.f(...)` work like the globals.
FUNCTIONS_MODULE = "functions"
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
            pool = Monty(
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


class _WorkerDemand:
    """The sandbox workers this process has checked out, the programs that wait
    for one, and holders: programs that keep their worker while they wait on
    their tool calls.

    Each waiting program claims one holder, which gives up its worker; the other
    holders keep theirs. A claim counts until its holder has returned its worker,
    or kept it because its dump does not fit. A waiting program claims again each
    time its checkout times out, so a claim that freed no worker for it is
    replaced. When a program stops waiting, claims beyond the programs still
    waiting are withdrawn from holders that have not given up yet.
    """

    def __init__(self, workers: int) -> None:
        self._lock = threading.Lock()
        self._workers = workers
        self._busy = 0
        self._waiting = 0
        # Wake-ups of the holders that keep their worker, oldest first.
        self._holders: dict[Callable[[], None], None] = {}
        # Claimed holders, also those that gave up and still have the worker.
        self._claimed: set[Callable[[], None]] = set()

    @property
    def all_busy(self) -> bool:
        with self._lock:
            return self._busy >= self._workers

    @contextmanager
    def worker(
        self, session: MontySession, wake: Callable[[], None]
    ) -> Iterator[MontySession]:
        """Check out the session's worker; raises TimeoutError when none is free.

        The claim on the program ends once its worker is back in the pool.
        """
        checked_out = False
        try:
            with session:
                with self._lock:
                    self._busy += 1
                checked_out = True
                yield session
        finally:
            if checked_out:
                with self._lock:
                    self._busy -= 1
                    self._claimed.discard(wake)

    @contextmanager
    def waiting(self) -> Iterator[None]:
        with self._lock:
            self._waiting += 1
        self.claim()
        try:
            yield
        finally:
            with self._lock:
                self._waiting -= 1
                withdrawable = [h for h in self._claimed if h in self._holders]
                excess = len(self._claimed) - self._waiting
                self._claimed.difference_update(withdrawable[: max(0, excess)])

    def claim(self) -> None:
        """Claim an unclaimed holder while fewer are claimed than programs wait."""
        with self._lock:
            if len(self._claimed) >= self._waiting:
                return
            holder = next((h for h in self._holders if h not in self._claimed), None)
            if holder is None:
                return
            self._claimed.add(holder)
        holder()

    def gives_up(self, wake: Callable[[], None]) -> bool:
        """Whether the holder of `wake` is claimed. A claimed holder stops
        holding; its claim counts until it returns or keeps its worker."""
        with self._lock:
            if wake not in self._claimed:
                return False
            self._holders.pop(wake, None)
            return True

    def kept(self, wake: Callable[[], None]) -> None:
        """The program that gave up its worker keeps it: its dump does not fit."""
        with self._lock:
            self._claimed.discard(wake)

    @contextmanager
    def holding(self, wake: Callable[[], None]) -> Iterator[None]:
        with self._lock:
            self._holders[wake] = None
        self.claim()
        try:
            yield
        finally:
            with self._lock:
                # A holder that did not give up drops a claim it had not seen.
                if wake in self._holders:
                    del self._holders[wake]
                    self._claimed.discard(wake)


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
    ) -> None:
        self.limits = limits
        self.function_names = frozenset(function_names)

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
        # The clock starts when the first worker is checked out, so time spent
        # queueing for a worker does not count.
        self.started: float | None = None
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

    def start_clock(self) -> None:
        if self.started is None:
            self.started = time.monotonic()
            self.deadline = self.started + self.limits.lifetime_seconds

    def abort_reason(self) -> "_Aborted | None":
        if self.cancellation.cancelled:
            return _Aborted("cancelled", "The execution was cancelled.")
        if time.monotonic() >= self.deadline:
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

    def wait_for_any(self, call_ids: list[int], *, yield_worker: bool = False) -> bool:
        """Wait until one of the calls or sleeps ends; True once one has.

        With `yield_worker`, the program keeps its worker while it waits and
        returns False as soon as another program waits for a worker.
        """
        wakeup = min(
            (self.sleeps[i] for i in call_ids if i in self.sleeps), default=math.inf
        )
        with _worker_demand.holding(self.wake.set) if yield_worker else nullcontext():
            while True:
                # Cleared before the checks, so a wake-up during them is not lost.
                self.wake.clear()
                self.check()
                self.start_queued()
                if any(self._finished(call_id) for call_id in call_ids):
                    return True
                if yield_worker and _worker_demand.gives_up(self.wake.set):
                    return False
                timeout = min(wakeup, self.deadline) - time.monotonic()
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
    only when the deadline can fall within the segment's compute limit. The pool
    replaces a killed worker.
    """
    lock = threading.Lock()
    computing = pid

    def kill() -> None:
        nonlocal computing
        with lock:
            if computing is not None:
                _kill_worker(computing)
                metrics.count_worker_lost("killed")
                computing = None

    remaining = run.deadline - time.monotonic()
    cancel_timer = (
        call_later(max(0.0, remaining), kill)
        if remaining < run.limits.max_cpu_seconds
        else None
    )
    try:
        with run.cancellation.on_cancel(kill):
            yield
    finally:
        if cancel_timer is not None:
            cancel_timer()
        # Under the lock, so the worker is never killed after it is returned.
        with lock:
            computing = None


def _start(
    session: MontySession, code: str, run: _Run
) -> SyncSnapshot | ProgramStopped:
    """Type-check and start the program.

    Invalid syntax and type errors in calls stop it; other diagnostics become
    notes.
    """
    with metrics.PROGRAM_START_DURATION.time():
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


def _suspend(run: _Run, waiting: ProgramWaiting) -> ProgramSuspended | None:
    """Dump a waiting program; None when the dump does not fit MAX_SUSPENDED_BYTES.

    The program's last dump size estimates the next, so a dump that cannot fit is
    skipped.
    """
    if run.last_dump_bytes > _suspended_bytes.free:
        metrics.count_suspension("over_budget")
        return None
    snapshot = waiting.state.dump()
    run.last_dump_bytes = len(snapshot)
    if not _suspended_bytes.reserve(len(snapshot)):
        metrics.count_suspension("over_budget")
        return None
    metrics.count_suspension("dumped")
    return ProgramSuspended(snapshot=snapshot, call_ids=waiting.call_ids)


def _functions_module(run: _Run, stubs: str) -> ExternalModule:
    """The `functions` module: every function of the program, typed by its stubs."""
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
    functions: ExternalModule,
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
                demand.enter_context(_worker_demand.waiting())
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
                    stack.enter_context(_worker_demand.worker(session, run.wake.set))
                    stack.enter_context(metrics.SANDBOX_WORKERS_BUSY.track_inprogress())
                    break
                except TimeoutError:
                    if time.monotonic() >= give_up:
                        raise
                    if waiting:
                        _worker_demand.claim()
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
    pool: Callable[[], Monty] = sandbox_pool,
) -> SandboxResult:
    """Run one program in a fresh interpreter. Raises the handler's BaseException.

    `cancellation` stops the program at once, also while it computes or waits.
    `on_print` receives the printed text and `on_yield` each yield_control() call,
    both on the driver thread. Nothing carries over from earlier programs; plain
    functions such as load() give a program outside state.
    The program waits at each await on unfinished tool calls or sleeps, and at
    each synchronous sleep. It keeps its worker while it waits, until another
    program waits for one; then it is dumped, its worker returned to the pool, and
    it resumes on any free worker once a call or sleep ends. When the program
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
            # A stop can surface as an exception that the program raises.
            commits_store=status == "completed"
            or (raised and run.abort_reason() is None),
            unawaited_calls=run.unawaited_calls() if status == "completed" else (),
            unstarted_calls=run.unstarted_calls() if status == "completed" else (),
        )

    resource_limits = _resource_limits(limits)
    functions = _functions_module(run, stubs)
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
                            suspended = _suspend(run, step)
                            if suspended is not None:
                                break
                            _worker_demand.kept(run.wake.set)
                            run.wait_for_any(step.call_ids)
                        step = _segment(session, run, partial(_resumed, step))
                if not isinstance(step, ProgramWaiting):
                    ended = step
                    break
                if suspended is not None:
                    run.wait_for_any(suspended.call_ids)
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
        metrics.SANDBOX_BUSY_REJECTIONS.inc()
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
            ended.output, "The value of the last expression", limits.max_output_chars
        )
    except (TypeError, ValueError) as error:
        return finish("completed", error=str(error))
    return finish("completed", result=repr(output))
