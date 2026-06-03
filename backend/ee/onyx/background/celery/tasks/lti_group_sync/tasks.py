"""Periodic Canvas (LTI) course roster → Onyx user group sync.

Iterates every Canvas-managed UserGroup (non-null `lti_context_id`), pulls the
course roster from the LTI Advantage NRPS endpoint captured at launch, and
overwrites the group's membership (matched to Onyx users by email) and name.

See docs/virtual-tutor/canvas-lti-student-group-sync.md.
"""

from celery import shared_task
from celery import Task
from redis.lock import Lock as RedisLock

from ee.onyx.db.user_group import ensure_lti_user_group
from ee.onyx.db.user_group import fetch_lti_managed_user_groups
from ee.onyx.db.user_group import sync_lti_group_membership_by_emails
from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_GENERIC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.lti_configs import lti_group_sync_enabled
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_redis_client
from onyx.server.lti.nrps import fetch_nrps_roster
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _sync_single_lti_group(
    *,
    user_group_id: int,
    lti_context_id: str,
    nrps_url: str | None,
) -> None:
    if not nrps_url:
        task_logger.warning(
            "LTI group %s (context %s) has no NRPS URL; skipping roster sync "
            "until a launch captures one",
            user_group_id,
            lti_context_id,
        )
        return

    roster = fetch_nrps_roster(nrps_url)
    emails = roster.active_member_emails()

    with get_session_with_current_tenant() as db_session:
        # Canvas is the source of truth for the name -- refresh it each sync.
        if roster.context_title:
            ensure_lti_user_group(
                db_session=db_session,
                lti_context_id=lti_context_id,
                course_title=roster.context_title,
                nrps_url=nrps_url,
            )
        sync_lti_group_membership_by_emails(
            db_session=db_session,
            user_group_id=user_group_id,
            emails=emails,
        )

    task_logger.info(
        "Synced LTI group %s (context %s): %d active roster members",
        user_group_id,
        lti_context_id,
        len(emails),
    )


@shared_task(
    name=OnyxCeleryTask.LTI_GROUP_SYNC,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    trail=False,
)
def lti_group_sync_task(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    if not lti_group_sync_enabled():
        return

    redis_client = get_redis_client()
    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.LTI_GROUP_SYNC_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # These runs should never overlap.
    if not lock_beat.acquire(blocking=False):
        return

    try:
        with get_session_with_current_tenant() as db_session:
            groups = [
                (group.id, group.lti_context_id, group.lti_nrps_url)
                for group in fetch_lti_managed_user_groups(db_session)
            ]

        for user_group_id, lti_context_id, nrps_url in groups:
            # lti_context_id is non-null by construction (it's the filter).
            if lti_context_id is None:
                continue
            # Keep the beat lock fresh across many groups; bail if we lost it.
            if not lock_beat.reacquire():
                task_logger.warning("Lost LTI group sync beat lock; stopping early")
                break
            try:
                _sync_single_lti_group(
                    user_group_id=user_group_id,
                    lti_context_id=lti_context_id,
                    nrps_url=nrps_url,
                )
            except OnyxError:
                # e.g. NRPS 403 (scope not granted) -- leave membership intact,
                # log, and continue with the remaining groups.
                task_logger.exception(
                    "LTI roster sync failed for group %s (context %s); "
                    "leaving membership unchanged",
                    user_group_id,
                    lti_context_id,
                )
            except ValueError:
                # e.g. group currently mid-Vespa-sync (not modifiable) -- retry
                # on the next run.
                task_logger.warning(
                    "Skipped LTI group %s (context %s); will retry next run",
                    user_group_id,
                    lti_context_id,
                )
    finally:
        if lock_beat.owned():
            lock_beat.release()
