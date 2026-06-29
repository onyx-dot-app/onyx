"""Run a callable in a throwaway child process so a native crash (SIGSEGV/SIGABRT),
a hang, or a runaway allocation kills the child instead of the caller. The parent
gets a typed error and decides how to recover.

For parse paths that feed untrusted bytes to native libs (PDF/image/office).
"""

import multiprocessing as mp
import signal
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any
from typing import TypeVar

from onyx.utils.logger import setup_logger

logger = setup_logger()

T = TypeVar("T")

_SIGTERM_GRACE_SECONDS = 5.0

_STATUS_OK = "ok"
_STATUS_EXC = "exc"
_STATUS_UNRELAYABLE = "unrelayable"


class IsolatedProcessError(Exception):
    """The isolated call did not return a value (crash, timeout, or lost result)."""


class IsolatedProcessCrashed(IsolatedProcessError):
    """Child was killed by a signal, e.g. a native abort/segfault in the callee."""

    def __init__(self, signal_number: int) -> None:
        self.signal_number = signal_number
        try:
            label = signal.Signals(signal_number).name
        except ValueError:
            label = f"signal {signal_number}"
        super().__init__(f"isolated process killed by {label}")


class IsolatedProcessTimeout(IsolatedProcessError):
    """Child exceeded the wall-clock timeout and was terminated."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        super().__init__(f"isolated process exceeded {timeout_seconds:g}s timeout")


def _apply_memory_limit(memory_limit_bytes: int) -> None:
    # Best-effort cap on address space so a runaway alloc fails in the child
    # instead of OOM-killing the pod. Not enforced everywhere (macOS ignores it).
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    except (ImportError, AttributeError, ValueError, OSError) as e:
        logger.debug("could not apply isolated-process memory limit: %s", e)


def _child_entrypoint(
    fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    memory_limit_bytes: int | None,
    conn: Connection,
) -> None:
    if memory_limit_bytes is not None:
        _apply_memory_limit(memory_limit_bytes)

    try:
        payload: tuple[str, Any] = (_STATUS_OK, fn(*args, **kwargs))
    except Exception as e:
        # Native crashes are signals (the parent sees those via the exit code), so
        # only fn's own exceptions land here. Relay them for the parent to re-raise.
        payload = (_STATUS_EXC, e)

    try:
        conn.send(payload)
    except Exception:
        # Unpicklable result/exception can't cross the pipe; relay its repr.
        conn.send((_STATUS_UNRELAYABLE, repr(payload[1])))
    finally:
        conn.close()


def run_in_isolated_process(
    fn: Callable[..., T],
    *args: Any,
    timeout: float,
    memory_limit_mb: int | None = None,
    **kwargs: Any,
) -> T:
    """Run ``fn(*args, **kwargs)`` in an isolated child process and return its result.

    fn's own exceptions are re-raised here unchanged. A signal kill (native crash)
    raises ``IsolatedProcessCrashed``, a timeout raises ``IsolatedProcessTimeout``,
    and a failure to start the child raises ``IsolatedProcessError`` (all subclass
    it, so callers can catch the base and fall back). fn and args must be picklable.
    """
    # forkserver, not spawn: children fork from a clean server and don't re-import
    # __main__. spawn re-imports it per child, which blows up inside the already
    # spawned indexing worker (its __main__ is the mp bootstrap, not a script).
    ctx = mp.get_context("forkserver")
    memory_limit_bytes = memory_limit_mb * 1024 * 1024 if memory_limit_mb else None

    # Result comes back over an anonymous pipe, not a temp file: nothing on disk
    # to tamper with, and no Queue feeder thread to deadlock on a big payload.
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_child_entrypoint,
        args=(fn, args, kwargs, memory_limit_bytes, send_conn),
    )
    try:
        try:
            proc.start()
        except Exception as e:
            logger.warning("could not start isolated process: %s", e)
            raise IsolatedProcessError(f"could not start isolated process: {e}") from e

        # Parent only reads; drop its write end so the pipe hits EOF when the child
        # dies (that's how a crash becomes visible).
        send_conn.close()

        if not recv_conn.poll(timeout):
            proc.terminate()
            proc.join(_SIGTERM_GRACE_SECONDS)
            if proc.is_alive():
                proc.kill()
                proc.join()
            raise IsolatedProcessTimeout(timeout)

        try:
            status, value = recv_conn.recv()
        except EOFError:
            # Pipe closed with no result: the child was killed by a signal.
            proc.join()
            if proc.exitcode is not None and proc.exitcode < 0:
                raise IsolatedProcessCrashed(-proc.exitcode)
            raise IsolatedProcessError(
                f"isolated process left no result (exit code {proc.exitcode})"
            )

        proc.join()
        if status == _STATUS_OK:
            return value
        if status == _STATUS_EXC and isinstance(value, BaseException):
            raise value
        logger.warning("isolated process returned an unrelayable result: %s", value)
        raise IsolatedProcessError(f"isolated process failed: {value!r}")
    finally:
        recv_conn.close()
        if proc.is_alive():
            proc.kill()
            proc.join()
