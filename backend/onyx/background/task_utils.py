"""Background task utilities.

Contains query-history report helpers (used by all deployment modes), the
shared enqueue path for user file deletes, and in-process background task
execution helpers for NO_VECTOR_DB mode:

- Atomic claim-and-mark helpers that prevent duplicate processing
- Drain loops that process all pending user file work
- The delete enqueue every request handler routes through

Each claim function runs a short-lived transaction: SELECT ... FOR UPDATE
SKIP LOCKED, UPDATE the row to remove it from future queries, COMMIT.
After the commit the row lock is released, but the row is no longer
eligible for re-claiming.  No long-lived sessions or advisory locks.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from celery import Celery
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.constants import (
    CELERY_USER_FILE_DELETE_TASK_EXPIRES,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
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
# Atomic claim-and-mark helpers
# ------------------------------------------------------------------
# Each function runs inside a single short-lived session/transaction:
#   1. SELECT ... FOR UPDATE SKIP LOCKED  (locks one eligible row)
#   2. UPDATE the row so it is no longer eligible
#   3. COMMIT  (releases the row lock)
# After the commit, no other drain loop can claim the same row.


def _claim_next_processing_file(db_session: Session) -> UUID | None:
    """Claim the next PROCESSING file by transitioning it to INDEXING.

    Returns the file id, or None when no eligible files remain.
    """
    file_id = db_session.execute(
        select(UserFile.id)
        .where(UserFile.status == UserFileStatus.PROCESSING)
        .order_by(UserFile.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if file_id is None:
        return None

    db_session.execute(
        sa.update(UserFile)
        .where(UserFile.id == file_id)
        .values(status=UserFileStatus.INDEXING)
    )
    db_session.commit()
    return file_id


def _claim_next_deleting_file(
    db_session: Session,
    exclude_ids: set[UUID] | None = None,
) -> UUID | None:
    """Claim the next DELETING file.

    No status transition needed — the impl deletes the row on success.
    The short-lived FOR UPDATE lock prevents concurrent claims.
    *exclude_ids* prevents re-processing the same file if the impl fails.
    """
    stmt = (
        select(UserFile.id)
        .where(UserFile.status == UserFileStatus.DELETING)
        .order_by(UserFile.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if exclude_ids:
        stmt = stmt.where(UserFile.id.notin_(exclude_ids))
    file_id = db_session.execute(stmt).scalar_one_or_none()
    db_session.commit()
    return file_id


def _claim_next_sync_file(
    db_session: Session,
    exclude_ids: set[UUID] | None = None,
) -> UUID | None:
    """Claim the next file needing project/persona sync.

    No status transition needed — the impl clears the sync flags on
    success.  The short-lived FOR UPDATE lock prevents concurrent claims.
    *exclude_ids* prevents re-processing the same file if the impl fails.
    """
    stmt = (
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
    )
    if exclude_ids:
        stmt = stmt.where(UserFile.id.notin_(exclude_ids))
    file_id = db_session.execute(stmt).scalar_one_or_none()
    db_session.commit()
    return file_id


# ------------------------------------------------------------------
# Drain loops — process *all* pending work of each type
# ------------------------------------------------------------------


def drain_processing_loop(tenant_id: str) -> None:
    """Process all pending PROCESSING user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        process_user_file_impl,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    while True:
        with get_session_with_current_tenant() as session:
            file_id = _claim_next_processing_file(session)
        if file_id is None:
            break
        try:
            process_user_file_impl(
                user_file_id=str(file_id),
                tenant_id=tenant_id,
                redis_locking=False,
            )
        except Exception:
            logger.exception("Failed to process user file %s", file_id)


def drain_delete_loop(tenant_id: str) -> None:
    """Delete all pending DELETING user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        delete_user_file_impl,
    )
    from onyx.chat.incognito import (
        sweep_incognito_generated_files,
        sweep_stale_incognito_user_files,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    failed: set[UUID] = set()
    while True:
        with get_session_with_current_tenant() as session:
            file_id = _claim_next_deleting_file(session, exclude_ids=failed)
        if file_id is None:
            break
        try:
            delete_user_file_impl(
                user_file_id=str(file_id),
                tenant_id=tenant_id,
                redis_locking=False,
            )
        except Exception:
            logger.exception("Failed to delete user file %s", file_id)
            failed.add(file_id)

    # Last, and never fatal: this loop is the whole delete path on lite
    # deployments, so a sweep that cannot reach Redis must not hold up ordinary
    # deletion. What it queues is picked up on the next pass.
    try:
        with get_session_with_current_tenant() as session:
            sweep_stale_incognito_user_files(session)
            # Always: the sweep also restarts the orphan clock on sessions it
            # found live, which is lost if only a queued file triggers this.
            session.commit()
            sweep_incognito_generated_files(session)
    except Exception:
        logger.exception("Stale incognito sweep failed")


def drain_project_sync_loop(tenant_id: str) -> None:
    """Sync all pending project/persona metadata for user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        project_sync_user_file_impl,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    failed: set[UUID] = set()
    while True:
        with get_session_with_current_tenant() as session:
            file_id = _claim_next_sync_file(session, exclude_ids=failed)
        if file_id is None:
            break
        try:
            project_sync_user_file_impl(
                user_file_id=str(file_id),
                tenant_id=tenant_id,
                redis_locking=False,
            )
        except Exception:
            logger.exception("Failed to sync user file %s", file_id)
            failed.add(file_id)


# ------------------------------------------------------------------
# Delete enqueue: the one path request handlers use
# ------------------------------------------------------------------


def send_user_file_delete_task(app: Celery, user_file_id: UUID, tenant_id: str) -> None:
    """Send one delete to the worker queue.

    Carries the expiry every send needs, so a backlog cannot grow without bound.
    """
    app.send_task(
        OnyxCeleryTask.DELETE_SINGLE_USER_FILE,
        kwargs={"user_file_id": str(user_file_id), "tenant_id": tenant_id},
        queue=OnyxCeleryQueues.USER_FILE_DELETE,
        priority=OnyxCeleryPriority.HIGH,
        expires=CELERY_USER_FILE_DELETE_TASK_EXPIRES,
    )


def enqueue_user_file_deletes(
    user_file_ids: Sequence[UUID],
    *,
    tenant_id: str,
    bg_tasks: BackgroundTasks,
) -> None:
    """Hand rows already marked DELETING to whatever drains them here.

    Lite deployments run no Celery, so the queue has no consumer and the work
    goes to an in-process drain that runs with the request rather than waiting
    on the recovery poll.
    """
    if not user_file_ids:
        return
    if DISABLE_VECTOR_DB:
        bg_tasks.add_task(drain_delete_loop, tenant_id)
        logger.info("Queued in-process delete for %d user file(s)", len(user_file_ids))
        return

    from onyx.background.celery.versioned_apps.client import app as client_app

    for user_file_id in user_file_ids:
        send_user_file_delete_task(client_app, user_file_id, tenant_id)
    logger.info("Queued delete task for %d user file(s)", len(user_file_ids))
