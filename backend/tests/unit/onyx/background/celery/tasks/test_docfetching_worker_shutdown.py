"""Guards the graceful-shutdown wiring: the process-global signal the
worker_shutting_down handler sets and the indexing watchdog polls, plus the
existence of the watchdog terminal-status constant the shutdown branch keys off.
"""

from onyx.background.celery.tasks.docfetching import worker_shutdown
from onyx.background.celery.tasks.models import IndexingWatchdogTerminalStatus


def test_worker_shutdown_signal_round_trips() -> None:
    worker_shutdown._worker_shutting_down.clear()
    try:
        assert worker_shutdown.is_worker_shutting_down() is False
        worker_shutdown.signal_worker_shutting_down()
        assert worker_shutdown.is_worker_shutting_down() is True
    finally:
        worker_shutdown._worker_shutting_down.clear()


def test_worker_shutdown_terminal_status_exists() -> None:
    assert (
        IndexingWatchdogTerminalStatus.TERMINATED_BY_WORKER_SHUTDOWN.value
        == "terminated_by_worker_shutdown"
    )
