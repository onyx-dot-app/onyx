"""Skills cleanup tasks — sweep orphaned bundle blobs and aged soft-deletes.

Two retention paths converge in one weekly sweep:

1. **Orphan blobs.** FileStore records with ``origin = SKILL_BUNDLE`` that are
   not referenced by any ``skill.bundle_file_id``. These accumulate when a
   create/replace request crashes after saving the blob but before the DB row
   commits. The 14-day cutoff guarantees we never race the in-flight commit.

2. **Aged soft-deletes.** ``Skill`` rows whose ``deleted_at`` is older than the
   retention window. Blob is deleted, then the row is hard-deleted, freeing
   the slug for reuse and bounding the soft-deleted row footprint.

The 14-day window preserves a small undelete affordance (engineer-only via DB
mutation) for accidental admin deletes. The sweep is idempotent: rerunning is a
no-op once nothing remains aged-out.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import FileRecord
from onyx.db.models import Skill
from onyx.file_store.file_store import FileStore
from onyx.file_store.file_store import get_default_file_store
from onyx.redis.redis_pool import get_redis_client

CLEANUP_RETENTION = timedelta(days=14)
TASK_TIMEOUT_SECONDS = 600  # 10 minutes — bounded by FileStore + DB I/O


def _orphan_skill_blob_ids(db_session: Session, older_than: timedelta) -> list[str]:
    """FileRecord rows with origin=SKILL_BUNDLE older than the cutoff that are
    not referenced by any Skill row (including soft-deleted ones).

    Including soft-deleted rows in the "referenced" set is important: aged
    soft-deletes are handled by the lifecycle path below, and we don't want
    the orphan path to delete a blob out from under it.
    """
    cutoff = datetime.now(tz=timezone.utc) - older_than
    referenced_subq = select(Skill.bundle_file_id)
    stmt = select(FileRecord.file_id).where(
        FileRecord.file_origin == FileOrigin.SKILL_BUNDLE,
        FileRecord.created_at < cutoff,
        FileRecord.file_id.not_in(referenced_subq),
    )
    return list(db_session.execute(stmt).scalars())


def _aged_soft_deleted_skills(
    db_session: Session, older_than: timedelta
) -> list[Skill]:
    cutoff = datetime.now(tz=timezone.utc) - older_than
    stmt = select(Skill).where(
        Skill.deleted_at.is_not(None),
        Skill.deleted_at < cutoff,
    )
    return list(db_session.execute(stmt).scalars())


def _delete_orphan_blobs(
    db_session: Session, file_store: FileStore, retention: timedelta
) -> int:
    deleted = 0
    for file_id in _orphan_skill_blob_ids(db_session, retention):
        try:
            file_store.delete_file(file_id, error_on_missing=False)
        except Exception:
            task_logger.exception(
                f"Failed to delete orphaned skill bundle blob {file_id}"
            )
            continue
        deleted += 1
        task_logger.info(f"Deleted orphaned skill bundle blob {file_id}")
    return deleted


def _delete_aged_soft_deleted_skills(
    db_session: Session, file_store: FileStore, retention: timedelta
) -> int:
    deleted = 0
    for skill in _aged_soft_deleted_skills(db_session, retention):
        # Spec ordering: blob first, then row. If the blob delete fails we
        # leave the row in place so the next sweep retries; if the row delete
        # later fails the blob is gone but the row's bundle_file_id points at
        # nothing — the next sweep finds it via the aged path again and
        # error_on_missing=False makes the retry idempotent.
        try:
            file_store.delete_file(skill.bundle_file_id, error_on_missing=False)
        except Exception:
            task_logger.exception(
                f"Failed to delete bundle blob for aged soft-deleted skill {skill.id}; "
                "leaving row for next sweep"
            )
            continue
        db_session.delete(skill)
        deleted += 1
        task_logger.info(
            f"Hard-deleted aged soft-deleted skill {skill.id} (slug={skill.slug})"
        )
    return deleted


def cleanup_orphaned_skill_blobs_impl(
    retention: timedelta = CLEANUP_RETENTION,
) -> tuple[int, int]:
    """Run the sweep once. Returns ``(orphans_deleted, aged_skills_deleted)``.

    Pulled out of the Celery wrapper so tests can drive it directly with a
    shorter retention window.
    """
    file_store = get_default_file_store()
    with get_session_with_current_tenant() as db_session:
        orphans = _delete_orphan_blobs(db_session, file_store, retention)
        aged = _delete_aged_soft_deleted_skills(db_session, file_store, retention)
        db_session.commit()
    return orphans, aged


@shared_task(
    name=OnyxCeleryTask.CLEANUP_ORPHANED_SKILL_BLOBS,
    bind=True,
    soft_time_limit=TASK_TIMEOUT_SECONDS,
    ignore_result=True,
)
def cleanup_orphaned_skill_blobs_task(
    self: Task, *, tenant_id: str  # noqa: ARG001
) -> None:
    redis_client = get_redis_client(tenant_id=tenant_id)
    lock: RedisLock = redis_client.lock(
        OnyxRedisLocks.CLEANUP_ORPHANED_SKILL_BLOBS_BEAT_LOCK,
        timeout=TASK_TIMEOUT_SECONDS,
    )
    if not lock.acquire(blocking=False):
        task_logger.info(
            "cleanup_orphaned_skill_blobs_task - lock not acquired, skipping"
        )
        return

    try:
        orphans, aged = cleanup_orphaned_skill_blobs_impl()
        task_logger.info(
            f"cleanup_orphaned_skill_blobs_task: removed {orphans} orphan blob(s) "
            f"and {aged} aged soft-deleted skill(s) for tenant {tenant_id}"
        )
    except Exception:
        task_logger.exception("Error in cleanup_orphaned_skill_blobs_task")
        raise
    finally:
        if lock.owned():
            lock.release()
