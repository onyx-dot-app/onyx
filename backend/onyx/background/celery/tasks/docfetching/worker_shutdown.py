"""Process-global flag that the docfetching worker is shutting down.

The ``worker_shutting_down`` handler sets it on SIGTERM. The indexing watchdog
polls it and interrupts its in-flight attempt for a fast checkpoint resume instead
of the heartbeat timeout. Both run in the same process (handler on the main thread,
watchdog on a pool thread), so a plain ``threading.Event`` is the right carrier.
"""

import threading

_worker_shutting_down = threading.Event()


def signal_worker_shutting_down() -> None:
    _worker_shutting_down.set()


def is_worker_shutting_down() -> bool:
    return _worker_shutting_down.is_set()
