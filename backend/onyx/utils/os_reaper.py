"""Reap orphaned child processes in spawned connector workers (Linux).

Chromium helpers orphaned by Playwright teardown re-parent to PID 1 (the
celery worker, which never wait()s) and accumulate as zombies. Spawned
connector children mark themselves as the subreaper and drain them instead.

Linux-only by nature, not as a shortcut: the pathology exists only where
PID 1 is a non-reaping worker (our containers). On macOS orphans re-parent
to launchd, which reaps them.

Only call the drains from a process whose subprocess usage is sequential and
fully owned — a blanket waitpid(-1) steals exit statuses from concurrent
waiters.
"""

import os
import signal
import sys
import time

from onyx.utils.logger import setup_logger

logger = setup_logger()

_PR_SET_CHILD_SUBREAPER = 36


def become_child_subreaper() -> bool:
    """Re-parent orphaned descendants to this process instead of PID 1."""
    if sys.platform != "linux":
        return False

    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            logger.warning(
                "become_child_subreaper: prctl failed errno=%s", ctypes.get_errno()
            )
            return False
    except Exception:
        logger.warning("become_child_subreaper: prctl unavailable", exc_info=True)
        return False

    return True


def reap_exited_children() -> int:
    """Reap already-exited (zombie) children without blocking; returns count."""
    if sys.platform != "linux":
        return 0

    reaped = 0
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break  # no children at all
        except OSError:
            logger.warning("reap_exited_children: waitpid failed", exc_info=True)
            break

        if pid == 0:
            break  # children exist but none have exited

        reaped += 1

    return reaped


def _live_child_pids() -> list[int]:
    """Direct children (adopted orphans included) that are still running."""
    me = os.getpid()
    pids = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                data = f.read()
            # comm may contain spaces; state and ppid follow the closing paren
            state, ppid = data[data.rindex(")") + 2 :].split()[:2]
            if int(ppid) == me and state != "Z":
                pids.append(int(entry))
        except (OSError, IndexError, ValueError):
            continue
    return pids


def reap_children_before_exit(grace_seconds: float = 2.0) -> int:
    """Exit-path drain: reap exited children, give still-running ones a short
    grace to finish, then SIGKILL the rest and reap them. A child left alive
    at exit would re-parent to PID 1 and zombify there when it dies."""
    if sys.platform != "linux":
        return 0

    reaped = reap_exited_children()
    deadline = time.monotonic() + grace_seconds
    while _live_child_pids() and time.monotonic() < deadline:
        time.sleep(0.05)
        reaped += reap_exited_children()

    # iterate: killing a child re-parents ITS children to us (we are the
    # subreaper), so new live children can appear mid-kill; bounded hard stop
    kill_deadline = time.monotonic() + 5.0
    killed = 0
    while time.monotonic() < kill_deadline:
        live = _live_child_pids()
        if not live:
            break
        for pid in live:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except OSError:
                pass
        time.sleep(0.05)
        reaped += reap_exited_children()

    if killed:
        logger.warning(
            "reap_children_before_exit: SIGKILLed %s straggler children", killed
        )

    reaped += reap_exited_children()
    return reaped


def install_sigterm_drain() -> None:
    """Make SIGTERM drain orphans before the process dies (Linux, main thread).

    Watchdogs cancel spawned children with SIGTERM; the default disposition
    kills the process instantly, stranding adopted zombies and live Chromium
    descendants on PID 1. Exits 143 after draining."""
    if sys.platform != "linux":
        return

    def _drain_and_exit(signum: int, frame: object) -> None:  # noqa: ARG001
        reap_children_before_exit()
        os._exit(128 + signal.SIGTERM)

    try:
        signal.signal(signal.SIGTERM, _drain_and_exit)
    except (ValueError, OSError):
        # not the main thread / exotic embedding — child startup must not fail
        logger.warning(
            "install_sigterm_drain: could not install handler", exc_info=True
        )
