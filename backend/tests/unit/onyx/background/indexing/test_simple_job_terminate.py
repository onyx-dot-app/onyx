"""Unit tests for `SimpleJob.terminate_and_wait`.

These tests do NOT exercise the full indexing watchdog. They only validate the
small primitive added so the watchdog can hard-kill a stuck spawned process
when its IndexAttempt has been finalized.

We need real OS processes here (multiprocessing.Process) - mocking would
defeat the purpose of testing termination semantics.
"""

import multiprocessing as mp
import os
import signal
import time

import pytest

from onyx.background.indexing.job_client import SimpleJob


def _ignore_sigterm_and_sleep_forever(ready_path: str) -> None:
    """Child entry point that ignores SIGTERM, simulating a hung connector
    that is not responsive to graceful shutdown signals.

    Writes to `ready_path` once SIGTERM is masked so the parent can avoid a
    race where it sends SIGTERM before the child has installed its handler.
    """
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(ready_path, "w") as f:
        f.write("ready")
    while True:
        time.sleep(0.1)


def _exit_quickly_on_sigterm(ready_path: str) -> None:
    """Child entry point that handles SIGTERM by exiting cleanly."""

    def _handler(_signum: int, _frame: object) -> None:
        os._exit(0)

    signal.signal(signal.SIGTERM, _handler)
    with open(ready_path, "w") as f:
        f.write("ready")
    while True:
        time.sleep(0.1)


def _wait_for_ready_file(path: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return
        time.sleep(0.05)
    raise TimeoutError(f"child never wrote ready file: {path}")


@pytest.fixture()
def ready_file(tmp_path) -> str:  # type: ignore[no-untyped-def]
    return str(tmp_path / "child_ready.txt")


def test_terminate_and_wait_returns_false_when_no_process() -> None:
    """A SimpleJob with no spawned process should be a no-op."""
    job = SimpleJob(id=0, process=None, queue=None)
    assert job.terminate_and_wait(sigterm_grace_seconds=1.0) is False


def test_terminate_and_wait_returns_false_when_process_already_exited(
    ready_file: str,
) -> None:
    """If the child already exited cleanly, terminate_and_wait shouldn't error
    and should report that there was nothing to do."""
    ctx = mp.get_context("spawn")
    process = ctx.Process(target=_exit_quickly_on_sigterm, args=(ready_file,))
    process.start()
    _wait_for_ready_file(ready_file)
    assert process.pid is not None
    os.kill(process.pid, signal.SIGTERM)
    process.join(timeout=5.0)
    assert not process.is_alive()

    job = SimpleJob(id=1, process=process, queue=None)
    assert job.terminate_and_wait(sigterm_grace_seconds=1.0) is False


def test_terminate_and_wait_kills_responsive_child_with_sigterm(
    ready_file: str,
) -> None:
    """A responsive child should be reaped by the SIGTERM stage; we should
    not need to escalate to SIGKILL."""
    ctx = mp.get_context("spawn")
    process = ctx.Process(target=_exit_quickly_on_sigterm, args=(ready_file,))
    process.start()
    _wait_for_ready_file(ready_file)

    job = SimpleJob(id=2, process=process, queue=None)
    assert job.terminate_and_wait(sigterm_grace_seconds=5.0) is True
    assert not process.is_alive()
    assert process.exitcode == 0


def test_terminate_and_wait_escalates_to_sigkill_for_unresponsive_child(
    ready_file: str,
) -> None:
    """If the child ignores SIGTERM, terminate_and_wait must escalate to SIGKILL
    so we never leave an orphaned subprocess attached to a worker thread.

    This is the exact scenario that motivated this change: a connector
    subprocess that is hung and unresponsive to SIGTERM was tying up a
    docfetching worker thread indefinitely.
    """
    ctx = mp.get_context("spawn")
    process = ctx.Process(target=_ignore_sigterm_and_sleep_forever, args=(ready_file,))
    process.start()
    _wait_for_ready_file(ready_file)

    job = SimpleJob(id=3, process=process, queue=None)
    start = time.monotonic()
    grace = 0.5
    assert job.terminate_and_wait(sigterm_grace_seconds=grace) is True
    elapsed = time.monotonic() - start

    assert not process.is_alive()
    assert process.exitcode == -signal.SIGKILL
    assert elapsed >= grace
    assert elapsed < grace + 5.0
