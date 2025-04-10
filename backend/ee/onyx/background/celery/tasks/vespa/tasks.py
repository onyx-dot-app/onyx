from typing import cast

from redis import Redis
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import delete_user_group
from ee.onyx.db.user_group import fetch_user_group
from ee.onyx.db.user_group import mark_user_group_as_synced
from ee.onyx.db.user_group import prepare_user_group_for_deletion
from onyx.background.celery.apps.app_base import task_logger
from onyx.db.enums import SyncStatus
from onyx.db.enums import SyncType
from onyx.db.sync_record import update_sync_record_status
from onyx.redis.redis_usergroup import RedisUserGroup
from onyx.utils.logger import setup_logger

logger = setup_logger()


def monitor_usergroup_taskset(
    tenant_id: str, key_bytes: bytes, r: Redis, db_session: Session
) -> None:
    """This function is likely to move in the worker refactor happening next."""
    fence_key = key_bytes.decode("utf-8")
    usergroup_id_str = RedisUserGroup.get_id_from_fence_key(fence_key)
    if not usergroup_id_str:
        task_logger.warning(f"Could not parse usergroup id from {fence_key}")
        return

    try:
        usergroup_id = int(usergroup_id_str)
    except ValueError:
        task_logger.exception(f"usergroup_id ({usergroup_id_str}) is not an integer!")
        raise

    rug = RedisUserGroup(tenant_id, usergroup_id)
    if not rug.fenced:
        return

    initial_count = rug.payload
    if initial_count is None:
        return

    count = cast(int, r.scard(rug.taskset_key))
    task_logger.info(
        f"User group sync progress: usergroup_id={usergroup_id} remaining={count} initial={initial_count}"
    )
    if count > 0:
        update_sync_record_status(
            db_session=db_session,
            entity_id=usergroup_id,
            sync_type=SyncType.USER_GROUP,
            sync_status=SyncStatus.IN_PROGRESS,
            num_docs_synced=count,
        )
        return

    user_group = fetch_user_group(db_session=db_session, user_group_id=usergroup_id)
    if user_group:
        usergroup_name = user_group.name
        try:
            if user_group.is_up_for_deletion:
                # this prepare should have been run when the deletion was scheduled,
                # but run it again to be sure we're ready to go
                mark_user_group_as_synced(db_session, user_group)
                prepare_user_group_for_deletion(db_session, usergroup_id)
                delete_user_group(db_session=db_session, user_group=user_group)

                update_sync_record_status(
                    db_session=db_session,
                    entity_id=usergroup_id,
                    sync_type=SyncType.USER_GROUP,
                    sync_status=SyncStatus.SUCCESS,
                    num_docs_synced=initial_count,
                )

                task_logger.info(
                    f"Deleted usergroup: name={usergroup_name} id={usergroup_id}"
                )
            else:
                mark_user_group_as_synced(db_session=db_session, user_group=user_group)

                update_sync_record_status(
                    db_session=db_session,
                    entity_id=usergroup_id,
                    sync_type=SyncType.USER_GROUP,
                    sync_status=SyncStatus.SUCCESS,
                    num_docs_synced=initial_count,
                )

                task_logger.info(
                    f"Synced usergroup. name={usergroup_name} id={usergroup_id}"
                )
        except Exception as e:
            update_sync_record_status(
                db_session=db_session,
                entity_id=usergroup_id,
                sync_type=SyncType.USER_GROUP,
                sync_status=SyncStatus.FAILED,
                num_docs_synced=initial_count,
            )
            raise e

    rug.reset()
