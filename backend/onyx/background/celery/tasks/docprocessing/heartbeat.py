import contextvars
import threading
from collections.abc import Callable

from onyx.configs.constants import INDEXING_WORKER_HEARTBEAT_INTERVAL
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.index_attempt import increment_heartbeat_counter__no_commit
from onyx.utils.logger import setup_logger

logger = setup_logger()


def start_heartbeat(
    index_attempt_id: int, on_beat: Callable[[], None] | None = None
) -> tuple[threading.Thread, threading.Event]:
    """Start a heartbeat thread for the given index attempt. `on_beat` runs
    on each beat too."""
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(INDEXING_WORKER_HEARTBEAT_INTERVAL):
            try:
                with get_session_with_current_tenant() as db_session:
                    increment_heartbeat_counter__no_commit(db_session, index_attempt_id)
                    db_session.commit()
            except Exception:
                logger.exception(
                    "Failed to update heartbeat counter for index attempt %s",
                    index_attempt_id,
                )
            if on_beat is None:
                continue
            try:
                on_beat()
            except Exception:
                logger.exception(
                    "Heartbeat callback failed for index attempt %s",
                    index_attempt_id,
                )

    # Ensure contextvars from the outer context are available in the thread
    context = contextvars.copy_context()
    thread = threading.Thread(target=context.run, args=(heartbeat_loop,), daemon=True)
    thread.start()
    return thread, stop_event


def stop_heartbeat(thread: threading.Thread, stop_event: threading.Event) -> None:
    """Stop the heartbeat thread"""
    stop_event.set()
    thread.join(timeout=5)  # Wait up to 5 seconds for clean shutdown
