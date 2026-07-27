"""Reap orphaned child processes in spawned connector workers (Linux).

Chromium helpers orphaned by Playwright browser teardown re-parent to the
container's PID 1 (the celery worker, which never wait()s) and accumulate as
zombies. Spawned connector children mark themselves as the subreaper instead
and drain the orphans before exiting.

Only call reap_exited_children from a process whose subprocess usage is
sequential and fully owned — a blanket waitpid(-1) steals exit statuses from
concurrent waiters.
"""

import os
import sys

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
            # no children at all
            break
        except OSError:
            logger.warning("reap_exited_children: waitpid failed", exc_info=True)
            break

        if pid == 0:
            # children exist but none have exited
            break

        reaped += 1

    return reaped
