"""Background task utilities.

Contains query-history report helpers (used by all deployment modes) and
in-process background task execution helpers for NO_VECTOR_DB mode:

- Atomic claim-and-mark helpers that prevent duplicate processing
- Drain loops that process all pending user file work

Each claim function runs a short-lived transaction: SELECT ... FOR UPDATE
SKIP LOCKED, UPDATE the row to remove it from future queries, COMMIT.
After the commit the row lock is released, but the row is no longer
eligible for re-claiming.  No long-lived sessions or advisory locks.
"""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
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


def _claim_next_deleting_file(db_session: Session) -> UUID | None:
    """Claim the next DELETING file.

    No status transition needed — the impl deletes the row on success.
    The short-lived FOR UPDATE lock prevents concurrent claims.
    """
    file_id = db_session.execute(
        select(UserFile.id)
        .where(UserFile.status == UserFileStatus.DELETING)
        .order_by(UserFile.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    # Commit to release the row lock promptly.
    db_session.commit()
    return file_id


def _claim_next_sync_file(db_session: Session) -> UUID | None:
    """Claim the next file needing project/persona sync.

    No status transition needed — the impl clears the sync flags on
    success.  The short-lived FOR UPDATE lock prevents concurrent claims.
    """
    file_id = db_session.execute(
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
        process_user_file_impl(
            user_file_id=str(file_id),
            tenant_id=tenant_id,
            redis_locking=False,
        )


def drain_delete_loop(tenant_id: str) -> None:
    """Delete all pending DELETING user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        delete_user_file_impl,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    while True:
        with get_session_with_current_tenant() as session:
            file_id = _claim_next_deleting_file(session)
        if file_id is None:
            break
        delete_user_file_impl(
            user_file_id=str(file_id),
            tenant_id=tenant_id,
            redis_locking=False,
        )


def drain_project_sync_loop(tenant_id: str) -> None:
    """Sync all pending project/persona metadata for user files."""
    from onyx.background.celery.tasks.user_file_processing.tasks import (
        project_sync_user_file_impl,
    )
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    while True:
        with get_session_with_current_tenant() as session:
            file_id = _claim_next_sync_file(session)
        if file_id is None:
            break
        project_sync_user_file_impl(
            user_file_id=str(file_id),
            tenant_id=tenant_id,
            redis_locking=False,
        )
