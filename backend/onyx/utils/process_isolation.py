"""Run a callable in a throwaway child process so a native crash (SIGSEGV/SIGABRT)
or a hang takes down the child, not the caller; the parent gets a typed error and
decides how to recover.

Uses subprocess, not multiprocessing: the indexing worker is a daemon process, and
daemons can't have multiprocessing children.
"""

import pickle
import signal
import subprocess
import sys
from collections.abc import Callable
from typing import Any
from typing import TypeVar

T = TypeVar("T")

_RUNNER_MODULE = "onyx.utils.isolated_runner"

STATUS_OK = "ok"
STATUS_EXC = "exc"
STATUS_UNRELAYABLE = "unrelayable"


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


def run_in_isolated_process(
    fn: Callable[..., T], *args: Any, timeout: float, **kwargs: Any
) -> T:
    """Run ``fn(*args, **kwargs)`` in a child process and return its result.

    fn's own exceptions are re-raised unchanged. A native crash raises
    ``IsolatedProcessCrashed`` and a timeout raises ``IsolatedProcessTimeout`` (both
    subclass ``IsolatedProcessError``, so callers can catch the base and fall back).
    fn and args must be picklable.
    """
    request = pickle.dumps((fn, args, kwargs))
    try:
        result = subprocess.run(
            [sys.executable, "-m", _RUNNER_MODULE],
            input=request,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # run() has already killed and reaped the child by the time this raises.
        raise IsolatedProcessTimeout(timeout)
    except OSError as e:
        raise IsolatedProcessError(f"could not start isolated process: {e}") from e

    if result.returncode < 0:  # killed by signal -returncode
        raise IsolatedProcessCrashed(-result.returncode)
    if result.returncode != 0 or not result.stdout:
        raise IsolatedProcessError(
            f"isolated process exited with code {result.returncode}"
        )

    # Trusted input: our own child's result, not external data.
    status, value = pickle.loads(result.stdout)  # noqa: S301
    if status == STATUS_OK:
        return value
    if status == STATUS_EXC and isinstance(value, BaseException):
        raise value
    raise IsolatedProcessError(f"isolated process failed: {value!r}")
