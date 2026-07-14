import contextvars
import threading

from sqlalchemy import update

from onyx.configs.constants import INDEXING_WORKER_HEARTBEAT_INTERVAL
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import IndexAttempt
from onyx.utils.logger import setup_logger

logger = setup_logger()

# After this many consecutive failed beats we escalate WARNING -> ERROR. A
# stalled heartbeat is dangerous: the stall watchdog reads the counter as a
# liveness signal, so a silently-wedged heartbeat (e.g. the write starving for a
# DB connection against the shared worker pool) can get a live attempt
# invalidated. Surfacing sustained failures loudly lets operators catch it.
_HEARTBEAT_FAILURE_ESCALATION_THRESHOLD = 3


def start_heartbeat(index_attempt_id: int) -> tuple[threading.Thread, threading.Event]:
    """Start a heartbeat thread for the given index attempt"""
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        consecutive_failures = 0
        while not stop_event.wait(INDEXING_WORKER_HEARTBEAT_INTERVAL):
            try:
                with get_session_with_current_tenant() as db_session:
                    db_session.execute(
                        update(IndexAttempt)
                        .where(IndexAttempt.id == index_attempt_id)
                        .values(heartbeat_counter=IndexAttempt.heartbeat_counter + 1)
                    )
                    db_session.commit()
                if consecutive_failures:
                    logger.info(
                        "Heartbeat for index attempt %s recovered after %s "
                        "consecutive failures",
                        index_attempt_id,
                        consecutive_failures,
                    )
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                # A single miss is tolerable; sustained misses mean the counter
                # is stalling while the worker may well be alive, which can lead
                # the watchdog to misclassify a healthy attempt as crashed.
                if consecutive_failures >= _HEARTBEAT_FAILURE_ESCALATION_THRESHOLD:
                    logger.error(
                        "Heartbeat for index attempt %s has failed %s consecutive "
                        "times (~%ss stalled) — the stall watchdog may misread this "
                        "attempt as crashed",
                        index_attempt_id,
                        consecutive_failures,
                        consecutive_failures * INDEXING_WORKER_HEARTBEAT_INTERVAL,
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "Failed to update heartbeat counter for index attempt %s "
                        "(consecutive_failures=%s)",
                        index_attempt_id,
                        consecutive_failures,
                        exc_info=True,
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
