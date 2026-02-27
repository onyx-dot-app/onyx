"""Background task utilities.

Contains query-history report helpers (used by all deployment modes) and
in-process background task execution helpers for NO_VECTOR_DB mode:

- Postgres advisory lock-based concurrency semaphore (10d)
- Drain loops that process all pending user file work (10e)
- Entry points wired to FastAPI BackgroundTasks (10c)

Advisory locks are session-level: they persist until explicitly released via
``pg_advisory_unlock`` or until the DB connection closes.  The semaphore
session is kept open for the entire drain loop so the slot stays held, and
released in a ``finally`` block before the connection returns to the pool.
"""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ------------------------------------------------------------------
# Query-history report helpers (pre-existing, used by all modes)
# ------------------------------------------------------------------

QUERY_REPORT_NAME_PREFIX = "query-history"


def construct_query_history_report_name(
    task_id: str,
) -> str:
    return f"{QUERY_REPORT_NAME_PREFIX}-{task_id}.csv"


def extract_task_id_from_query_history_report_name(name: str) -> str:
    return name.removeprefix(f"{QUERY_REPORT_NAME_PREFIX}-").removesuffix(".csv")


# ------------------------------------------------------------------
# Postgres advisory lock semaphore (NO_VECTOR_DB mode)
# ------------------------------------------------------------------

BACKGROUND_TASK_SLOT_BASE = 10_000
BACKGROUND_TASK_MAX_CONCURRENCY = 4


def try_acquire_semaphore_slot(db_session: Session) -> int | None:
    """Try to acquire one of N advisory lock slots.

    Returns the slot number (0-based) if acquired, ``None`` if all slots are
    taken.  ``pg_try_advisory_lock`` is non-blocking — returns ``false``
    immediately when the lock is held by another session.
    """
    for slot in range(BACKGROUND_TASK_MAX_CONCURRENCY):
        lock_id = BACKGROUND_TASK_SLOT_BASE + slot
        acquired = db_session.execute(
            text("SELECT pg_try_advisory_lock(:id)"),
            {"id": lock_id},
        ).scalar()
        if acquired:
            return slot
    return None


def release_semaphore_slot(db_session: Session, slot: int) -> None:
    """Release a previously acquired advisory lock slot."""
    lock_id = BACKGROUND_TASK_SLOT_BASE + slot
    db_session.execute(
        text("SELECT pg_advisory_unlock(:id)"),
        {"id": lock_id},
    )


# ------------------------------------------------------------------
# Work-claiming helpers (FOR UPDATE SKIP LOCKED)
# ------------------------------------------------------------------


def _claim_next_processing_file(db_session: Session) -> UUID | None:
    """Claim the next file in PROCESSING status."""
    return db_session.execute(
        select(UserFile.id)
        .where(UserFile.status == UserFileStatus.PROCESSING)
        .order_by(UserFile.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()


def _claim_next_deleting_file(db_session: Session) -> UUID | None:
    """Claim the next file in DELETING status."""
    return db_session.execute(
        select(UserFile.id)
        .where(UserFile.status == UserFileStatus.DELETING)
        .order_by(UserFile.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()


def _claim_next_sync_file(db_session: Session) -> UUID | None:
    """Claim the next file needing project/persona sync."""
    return db_session.execute(
        select(UserFile.id)
        .where(
            sa.and_(
                sa.or_(
                    UserFile.needs_project_sync.is_(True),
                    UserFile.needs_persona_sync.is_(True),
                ),
                UserFile.status == UserFileStatus.COMPLETED,
            )
        )
        .order_by(UserFile.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()


# ------------------------------------------------------------------
# Drain loops — acquire a semaphore slot then process *all* pending work
# ------------------------------------------------------------------


def drain_processing_loop(tenant_id: str) -> None:
    """Process all pending PROCESSING user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        _process_user_file_impl,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    with get_session_with_current_tenant() as sem_session:
        slot = try_acquire_semaphore_slot(sem_session)
        if slot is None:
            logger.info("drain_processing_loop - All semaphore slots taken, skipping")
            return

        try:
            while True:
                with get_session_with_current_tenant() as claim_session:
                    file_id = _claim_next_processing_file(claim_session)
                if file_id is None:
                    break
                _process_user_file_impl(
                    user_file_id=str(file_id),
                    tenant_id=tenant_id,
                    redis_locking=False,
                )
        finally:
            release_semaphore_slot(sem_session, slot)


def drain_delete_loop(tenant_id: str) -> None:
    """Delete all pending DELETING user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        _delete_user_file_impl,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    with get_session_with_current_tenant() as sem_session:
        slot = try_acquire_semaphore_slot(sem_session)
        if slot is None:
            logger.info("drain_delete_loop - All semaphore slots taken, skipping")
            return

        try:
            while True:
                with get_session_with_current_tenant() as claim_session:
                    file_id = _claim_next_deleting_file(claim_session)
                if file_id is None:
                    break
                _delete_user_file_impl(
                    user_file_id=str(file_id),
                    tenant_id=tenant_id,
                    redis_locking=False,
                )
        finally:
            release_semaphore_slot(sem_session, slot)


def drain_project_sync_loop(tenant_id: str) -> None:
    """Sync all pending project/persona metadata for user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        _project_sync_user_file_impl,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    with get_session_with_current_tenant() as sem_session:
        slot = try_acquire_semaphore_slot(sem_session)
        if slot is None:
            logger.info("drain_project_sync_loop - All semaphore slots taken, skipping")
            return

        try:
            while True:
                with get_session_with_current_tenant() as claim_session:
                    file_id = _claim_next_sync_file(claim_session)
                if file_id is None:
                    break
                _project_sync_user_file_impl(
                    user_file_id=str(file_id),
                    tenant_id=tenant_id,
                    redis_locking=False,
                )
        finally:
            release_semaphore_slot(sem_session, slot)
