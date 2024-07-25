from datetime import timedelta

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from danswer.configs.constants import DocumentSource
from danswer.db.models import PermissionSyncRun
from danswer.db.models import PermissionSyncStatus
from danswer.utils.logger import setup_logger

logger = setup_logger()


def mark_all_inprogress_permission_sync_failed(
    db_session: Session,
) -> None:
    stmt = (
        update(PermissionSyncRun)
        .where(PermissionSyncRun.status == PermissionSyncStatus.IN_PROGRESS)
        .values(status=PermissionSyncStatus.FAILED)
    )
    db_session.execute(stmt)
    db_session.commit()


def get_perm_sync_attempt(attempt_id: int, db_session: Session) -> PermissionSyncRun:
    stmt = select(PermissionSyncRun).where(PermissionSyncRun.id == attempt_id)
    try:
        return db_session.scalars(stmt).one()
    except NoResultFound:
        raise ValueError(f"No PermissionSyncRun found with id {attempt_id}")


def expire_perm_sync_timed_out(
    timeout_hours: int,
    db_session: Session,
) -> None:
    cutoff_time = func.now() - timedelta(hours=timeout_hours)

    update_stmt = (
        update(PermissionSyncRun)
        .where(
            PermissionSyncRun.status == PermissionSyncStatus.IN_PROGRESS,
            PermissionSyncRun.updated_at < cutoff_time,
        )
        .values(status=PermissionSyncStatus.FAILED, error_msg="timed out")
    )

    db_session.execute(update_stmt)
    db_session.commit()


def create_perm_sync(
    source_type: DocumentSource,
    group_update: bool,
    cc_pair_id: int | None,
    db_session: Session,
) -> PermissionSyncRun:
    new_run = PermissionSyncRun(
        source_type=source_type,
        status=PermissionSyncStatus.IN_PROGRESS,
        group_update=group_update,
        cc_pair_id=cc_pair_id,
    )

    db_session.add(new_run)
    db_session.commit()

    return new_run
