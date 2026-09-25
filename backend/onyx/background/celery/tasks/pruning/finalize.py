"""Helpers for finalizing pruning SyncRecord state.

Extracted from connector_pruning_generator_task so the finalization
logic can be tested without importing the full Celery application.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from onyx.utils.logger import setup_logger

logger = setup_logger()


def handle_pre_fanout_pruning_failure(
    db_session: Session,
    cc_pair_id: int,
    reset_pruning_state: Callable[[], Any],
) -> None:
    """Finalize the pruning SyncRecord as FAILED, then reset Redis state.

    Called from connector_pruning_generator_task when connector enumeration
    fails before fan-out (generator_complete is None).

    Ordering guarantee:
        1. DB record transitions to FAILED while the fence still exists.
        2. Redis fence/taskset is cleared.

    If DB finalization fails, Redis cleanup still runs so the fence does
    not stay dirty forever.  The original DB error is re-raised after
    cleanup so the caller's logging / backoff still fires.
    """
    db_error: BaseException | None = None
    try:
        _finalize_sync_record_as_failed(db_session, cc_pair_id)
    except Exception as exc:
        db_error = exc
        logger.exception(
            "Failed to finalize SyncRecord as FAILED: cc_pair=%s", cc_pair_id
        )
    finally:
        reset_pruning_state()

    if db_error is not None:
        raise db_error


def _finalize_sync_record_as_failed(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    """Mark the pruning SyncRecord as FAILED in the database."""
    # Lazy import to avoid pulling in fastapi_users_db_sqlalchemy at
    # module-import time (onyx.db.models → fastapi_users_db_sqlalchemy).
    from onyx.db.enums import SyncStatus, SyncType
    from onyx.db.sync_record import update_sync_record_status

    update_sync_record_status(
        db_session=db_session,
        entity_id=cc_pair_id,
        sync_type=SyncType.PRUNING,
        sync_status=SyncStatus.FAILED,
        num_docs_synced=0,
    )
