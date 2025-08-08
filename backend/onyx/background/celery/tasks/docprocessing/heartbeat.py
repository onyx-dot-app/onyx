import threading

from sqlalchemy import update

from onyx.configs.constants import INDEXING_WORKER_HEARTBEAT_INTERVAL
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import IndexAttempt


def start_heartbeat(index_attempt_id: int) -> tuple[threading.Thread, threading.Event]:
    """Start a heartbeat thread for the given index attempt"""
    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(INDEXING_WORKER_HEARTBEAT_INTERVAL):
            try:
                with get_session_with_current_tenant() as db_session:
                    db_session.execute(
                        update(IndexAttempt)
                        .where(IndexAttempt.id == index_attempt_id)
                        .values(heartbeat_counter=IndexAttempt.heartbeat_counter + 1)
                    )
                    db_session.commit()
            except Exception:
                # Silently continue if heartbeat fails
                pass

    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    return thread, stop_event


def stop_heartbeat(thread: threading.Thread, stop_event: threading.Event) -> None:
    """Stop the heartbeat thread"""
    stop_event.set()
    thread.join(timeout=5)  # Wait up to 5 seconds for clean shutdown
