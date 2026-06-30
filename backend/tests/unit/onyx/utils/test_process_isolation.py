"""The process-isolation helper must convert a native child crash and a hang into
typed parent-side exceptions, while passing normal return values and ordinary
exceptions through unchanged."""

import ctypes
import multiprocessing as mp
import operator
import os
import time

import pytest

from onyx.utils.process_isolation import IsolatedProcessCrashed
from onyx.utils.process_isolation import IsolatedProcessTimeout
from onyx.utils.process_isolation import run_in_isolated_process


def test_returns_value() -> None:
    assert run_in_isolated_process(abs, -42, timeout=30) == 42


def test_passes_kwargs() -> None:
    assert run_in_isolated_process(int, "ff", base=16, timeout=30) == 255


def test_large_result_crosses_the_boundary() -> None:
    out = run_in_isolated_process(operator.mul, "ab", 3_000_000, timeout=60)
    assert len(out) == 6_000_000


def test_ordinary_exception_is_reraised() -> None:
    with pytest.raises(ValueError):
        run_in_isolated_process(int, "not-an-int", timeout=30)


def test_native_abort_becomes_crash() -> None:
    with pytest.raises(IsolatedProcessCrashed) as exc_info:
        run_in_isolated_process(os.abort, timeout=30)
    # SIGABRT, the signal libpdfium raises on a malformed PDF
    assert exc_info.value.signal_number == 6


def test_native_segfault_becomes_crash() -> None:
    # Null-pointer deref segfaults the child; the parent must see a crash.
    with pytest.raises(IsolatedProcessCrashed):
        run_in_isolated_process(ctypes.string_at, 0, timeout=30)


def test_timeout_is_enforced_and_child_reaped() -> None:
    started = time.monotonic()
    with pytest.raises(IsolatedProcessTimeout):
        run_in_isolated_process(time.sleep, 30, timeout=1)
    # returns near the timeout, not after the full 30s sleep
    assert time.monotonic() - started < 15


def _isolate_from_within(queue: "mp.Queue") -> None:
    try:
        queue.put(("ok", run_in_isolated_process(abs, -7, timeout=30)))
    except Exception as e:
        queue.put(("err", repr(e)))


def test_works_when_caller_is_a_daemon_process() -> None:
    # The indexing worker runs as a daemon, and daemons can't have multiprocessing
    # children. Isolation must still work from there (it shells out to subprocess).
    ctx = mp.get_context("spawn")
    queue: "mp.Queue" = ctx.Queue()
    proc = ctx.Process(target=_isolate_from_within, args=(queue,))
    proc.daemon = True
    proc.start()
    proc.join(60)
    assert proc.exitcode == 0, proc.exitcode
    status, value = queue.get(timeout=5)
    assert status == "ok", value
    assert value == 7
