"""Old-index reclamation: delete every reclaim-tracked PAST index after a reindex.

`check_for_old_index_reclaim` (beat scheduler, primary) is lightweight — it just fans
out one `run_old_index_reclaim_task` per reclaimable PAST row onto the `index_reclaim`
queue (light worker), so the heavy deletion never runs on the primary beat. Each task
steps its `SearchSettings` row through the state machine:

    PENDING  -> (port drained) fire consented cc_pair deletions, stamp soak anchor -> SOAKING
    SOAKING  -> (soak elapsed + new index can serve)                                -> DELETING
    DELETING -> (old index data gone, count-verified)                               -> RECLAIMED (row kept)

A per-row lock makes a duplicate/concurrent dispatch for the same row a no-op, so a
slow whale can't block newer rows or pile up. Every step is idempotent, so a crash
between an OpenSearch side-effect and its DB commit is recovered by re-running the step
next tick. A step that raises bumps the row's attempt counter and parks it BLOCKED at
the cap (alerted). The whole feature no-ops while `OLD_INDEX_RECLAIM_ENABLED` is False
(the kill switch / dark ship).
"""

import time
from datetime import datetime, timedelta, timezone

from celery import Celery, Task, shared_task
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.configs.app_configs import (
    OLD_INDEX_RECLAIM_ENABLED,
    OLD_INDEX_RECLAIM_MAX_ATTEMPTS,
    OLD_INDEX_RECLAIM_MAX_PER_RUN,
    OLD_INDEX_RETENTION_HOURS,
)
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.connector_credential_pair import (
    mark_cc_pairs_deleting_if_still_wont_port__no_commit,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexReclaimStatus
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import is_active_port_backfill_source
from onyx.db.search_settings import (
    advance_to_deleting__no_commit,
    advance_to_reclaimed__no_commit,
    advance_to_soaking__no_commit,
    fetch_reclaimable_past_settings,
    get_current_search_settings,
    get_search_settings_by_id,
    record_failure__no_commit,
)
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.index_reclaim import (
    ReclaimOutcome,
    reclaim_index_data,
)
from onyx.redis.redis_pool import get_redis_client
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

_RECLAIM_BEAT_SOFT_TIME_LIMIT = 60 * 5
_RECLAIM_TASK_SOFT_TIME_LIMIT = 60 * 5

# Per-DELETING-row wall-clock budget. On a whale (multi-tenant delete_by_query is
# bounded per call), loop many bounded batches within one dispatch so it drains in
# hours, not one batch per 30-min tick. Celery time limits are inert under thread
# pools, so this self-imposed budget is the real bound.
_DELETE_TIME_BUDGET_S = 60

# Per-row lock TTL. Must exceed a single dispatch's max runtime (the delete budget +
# overhead) so it isn't stolen mid-run; a dead worker's lock expires and the row is
# retried next tick.
_RECLAIM_TASK_LOCK_TTL = 60 * 5

_ACTIONABLE_RECLAIM_STATUSES = (
    IndexReclaimStatus.PENDING,
    IndexReclaimStatus.SOAKING,
    IndexReclaimStatus.DELETING,
)


def _reclaim_row_lock_key(search_settings_id: int) -> str:
    return f"{OnyxRedisLocks.OLD_INDEX_RECLAIM_LOCK_PREFIX}:{search_settings_id}"


def _new_index_can_serve(index_name: str) -> bool:
    """The new PRESENT index is healthy enough to serve before we delete the old one.
    Gate on non-red (yellow is normal on single-node: replicas unassigned but primaries
    up) plus a match-all count that proves the query path actually answers."""
    client = OpenSearchIndexClient(index_name=index_name)
    try:
        if not client.index_exists():
            return False
        health = client.cluster_health(index=index_name, level="indices")
        if health.get("status") == "red":
            return False
        client.count_by_query({"query": {"match_all": {}}})
        return True
    finally:
        client.close()


def _drive_pending(
    db_session: Session,
    celery_app: Celery,
    tenant_id: str,
    search_settings: SearchSettings,
) -> None:
    """PENDING: wait until nothing reads the old index anymore (swap done + port
    drained — the single completeness gate, correct for INSTANT too), then atomically
    move the still-not-recoverable consented connectors to DELETING and start the soak."""
    if is_active_port_backfill_source(db_session, search_settings.id):
        return

    consented = search_settings.pending_cc_pair_deletions or []
    # Atomic conditional transition (re-validation + state change in one UPDATE) so a
    # connector re-activated after consent was captured can't be clobbered into DELETING.
    deleted = mark_cc_pairs_deleting_if_still_wont_port__no_commit(
        db_session, consented
    )
    advanced = advance_to_soaking__no_commit(search_settings)
    db_session.commit()

    if deleted:
        # Kick the connector-deletion pipeline (crash-resumable) now that DELETING is
        # committed and the worker can see it; mirrors administrative.py's delete trigger.
        celery_app.send_task(
            OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
            priority=OnyxCeleryPriority.HIGH,
            kwargs={"tenant_id": tenant_id},
            expires=BEAT_EXPIRES_DEFAULT,
        )
    if advanced:
        task_logger.info(
            "Old-index reclaim %s -> SOAKING (index=%s, cc_pairs deleted=%d).",
            search_settings.id,
            search_settings.index_name,
            len(deleted),
        )


def _drive_soaking(db_session: Session, search_settings: SearchSettings) -> None:
    """SOAKING: wait out the retention window, then require the new PRESENT index can
    serve before deleting the old one."""
    anchor = search_settings.reclaim_stopped_reading_at
    if anchor is None:
        return
    if datetime.now(timezone.utc) - anchor < timedelta(hours=OLD_INDEX_RETENTION_HOURS):
        return

    new_present = get_current_search_settings(db_session)
    if not _new_index_can_serve(new_present.index_name):
        task_logger.info(
            "Old-index reclaim %s: soak elapsed but new index %s can't serve yet; waiting.",
            search_settings.id,
            new_present.index_name,
        )
        return

    if advance_to_deleting__no_commit(search_settings):
        db_session.commit()
        task_logger.info(
            "Old-index reclaim %s -> DELETING (index=%s).",
            search_settings.id,
            search_settings.index_name,
        )


def _drive_deleting(db_session: Session, search_settings: SearchSettings) -> None:
    """DELETING: delete the old index's data, looping bounded batches within a time
    budget so a whale drains fast. On COMPLETE (count-verified empty) mark the row
    RECLAIMED and KEEP it (we only delete the OpenSearch index, not the PAST row).
    INCOMPLETE leaves it DELETING for next tick."""
    index_name = search_settings.index_name
    settings_id = search_settings.id
    tenant_id = get_current_tenant_id()
    deadline = time.monotonic() + _DELETE_TIME_BUDGET_S

    while True:
        outcome = reclaim_index_data(index_name, MULTI_TENANT, tenant_id)
        if outcome == ReclaimOutcome.COMPLETE:
            advance_to_reclaimed__no_commit(search_settings)
            db_session.commit()
            task_logger.info(
                "Old-index reclaim %s RECLAIMED; index %s data gone, PAST row kept.",
                settings_id,
                index_name,
            )
            return

        # a bounded batch was deleted (progress) — reset attempts so a long drain can't trip BLOCKED
        search_settings.reclaim_attempts = 0
        db_session.commit()
        if time.monotonic() >= deadline:
            task_logger.info(
                "Old-index reclaim %s still draining index %s; resuming next tick.",
                settings_id,
                index_name,
            )
            return


def run_old_index_reclaim(
    db_session: Session,
    celery_app: Celery,
    tenant_id: str,
    search_settings: SearchSettings,
) -> None:
    """Drive one reclaim row a single step. Any step failure is recorded against the
    row and parks it BLOCKED at the attempt cap (alerted); the next tick retries."""
    settings_id = search_settings.id
    try:
        status = search_settings.reclaim_status
        if status == IndexReclaimStatus.PENDING:
            _drive_pending(db_session, celery_app, tenant_id, search_settings)
        elif status == IndexReclaimStatus.SOAKING:
            _drive_soaking(db_session, search_settings)
        elif status == IndexReclaimStatus.DELETING:
            _drive_deleting(db_session, search_settings)
    except Exception as e:
        db_session.rollback()
        row = get_search_settings_by_id(db_session, settings_id)
        if row is None:
            return
        blocked = record_failure__no_commit(row, str(e), OLD_INDEX_RECLAIM_MAX_ATTEMPTS)
        db_session.commit()
        if blocked:
            task_logger.error(
                "[ALERT] Old-index reclaim %s BLOCKED after %d failures (index=%s): %s",
                settings_id,
                OLD_INDEX_RECLAIM_MAX_ATTEMPTS,
                row.index_name,
                e,
            )
        else:
            task_logger.warning(
                "Old-index reclaim %s step failed (attempt %d/%d): %s",
                settings_id,
                row.reclaim_attempts,
                OLD_INDEX_RECLAIM_MAX_ATTEMPTS,
                e,
            )


def execute_old_index_reclaim(
    celery_app: Celery, tenant_id: str, search_settings_id: int
) -> None:
    """Body of run_old_index_reclaim_task (testable): under the per-row lock, drive one
    reclaim step for this PAST index. The lock (TTL) makes a duplicate/concurrent
    dispatch for the same row a no-op and self-heals if a worker dies mid-run."""
    if not OLD_INDEX_RECLAIM_ENABLED:
        return
    redis_client = get_redis_client()
    row_lock: RedisLock = redis_client.lock(
        _reclaim_row_lock_key(search_settings_id),
        timeout=_RECLAIM_TASK_LOCK_TTL,
    )
    if not row_lock.acquire(blocking=False):
        return
    try:
        with get_session_with_current_tenant() as db_session:
            search_settings = get_search_settings_by_id(db_session, search_settings_id)
            if (
                search_settings is None
                or search_settings.reclaim_status not in _ACTIONABLE_RECLAIM_STATUSES
            ):
                return
            run_old_index_reclaim(db_session, celery_app, tenant_id, search_settings)
    finally:
        if row_lock.owned():
            row_lock.release()


def run_check_for_old_index_reclaim(tenant_id: str, celery_app: Celery) -> int | None:
    """Beat body (testable): fan out one run-reclaim task per reclaimable PAST index
    onto the index_reclaim queue, so the deletion runs on the light worker, not
    the primary beat. Rows already being drained (per-row lock held) are skipped, so a
    slow whale can't block newer rows or pile up duplicates. Returns the number of
    tasks enqueued, or None if disabled / the beat lock was contended."""
    if not OLD_INDEX_RECLAIM_ENABLED:
        return None

    redis_client = get_redis_client()
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CHECK_OLD_INDEX_RECLAIM_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )
    if not lock_beat.acquire(blocking=False):
        return None

    enqueued = 0
    try:
        with get_session_with_current_tenant() as db_session:
            settings_ids = [
                ss.id
                for ss in fetch_reclaimable_past_settings(
                    db_session, limit=OLD_INDEX_RECLAIM_MAX_PER_RUN
                )
            ]
        for settings_id in settings_ids:
            if redis_client.lock(_reclaim_row_lock_key(settings_id)).locked():
                continue  # a run task is already draining this row
            celery_app.send_task(
                OnyxCeleryTask.RUN_OLD_INDEX_RECLAIM,
                kwargs={"tenant_id": tenant_id, "search_settings_id": settings_id},
                queue=OnyxCeleryQueues.INDEX_RECLAIM,
                priority=OnyxCeleryPriority.MEDIUM,
                expires=BEAT_EXPIRES_DEFAULT,
            )
            enqueued += 1
    finally:
        if lock_beat.owned():
            lock_beat.release()

    return enqueued


@shared_task(
    name=OnyxCeleryTask.RUN_OLD_INDEX_RECLAIM,
    soft_time_limit=_RECLAIM_TASK_SOFT_TIME_LIMIT,
    bind=True,
)
def run_old_index_reclaim_task(
    self: Task, *, tenant_id: str, search_settings_id: int
) -> None:
    execute_old_index_reclaim(self.app, tenant_id, search_settings_id)


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_OLD_INDEX_RECLAIM,
    soft_time_limit=_RECLAIM_BEAT_SOFT_TIME_LIMIT,
    bind=True,
)
def check_for_old_index_reclaim(self: Task, *, tenant_id: str) -> int | None:
    return run_check_for_old_index_reclaim(tenant_id, self.app)
