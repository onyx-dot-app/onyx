from typing import cast

from redis import Redis
from sqlalchemy.orm import Session

from danswer.background.celery.celery_app import task_logger
from danswer.background.celery.celery_redis import RedisUserGroup
from danswer.utils.logger import setup_logger
from ee.danswer.db.user_group import delete_user_group
from ee.danswer.db.user_group import fetch_user_group
from ee.danswer.db.user_group import mark_user_group_as_synced

logger = setup_logger()


def monitor_usergroup_taskset(key_bytes: bytes, r: Redis, db_session: Session) -> None:
    """This function is likely to move in the worker refactor happening next."""
    fence_key = key_bytes.decode("utf-8")
    usergroup_id = RedisUserGroup.get_id_from_fence_key(fence_key)
    if not usergroup_id:
        task_logger.warning(f"Could not parse usergroup id from {fence_key}")
        return

    rug = RedisUserGroup(usergroup_id)
    fence_value = r.get(rug.fence_key)
    if fence_value is None:
        return

    try:
        initial_count = int(cast(int, fence_value))
    except ValueError:
        task_logger.error("The value is not an integer.")
        return

    count = cast(int, r.scard(rug.taskset_key))
    task_logger.info(
        f"User group sync progress: usergroup_id={usergroup_id} remaining={count} initial={initial_count}"
    )
    if count > 0:
        return

    user_group = fetch_user_group(db_session=db_session, user_group_id=usergroup_id)
    if user_group:
        if user_group.is_up_for_deletion:
            delete_user_group(db_session=db_session, user_group=user_group)
            task_logger.info(f"Deleted usergroup. id='{usergroup_id}'")
        else:
            mark_user_group_as_synced(db_session=db_session, user_group=user_group)
            task_logger.info(f"Synced usergroup. id='{usergroup_id}'")

    r.delete(rug.taskset_key)
    r.delete(rug.fence_key)
