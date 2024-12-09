from sqlalchemy.orm import Session

from danswer.db.tasks import check_task_is_live_and_not_timed_out
from danswer.db.tasks import get_latest_task
from danswer.utils.logger import setup_logger
from ee.danswer.background.task_name_builders import name_chat_ttl_task

logger = setup_logger()


def should_perform_chat_ttl_check(
    retention_limit_days: int | None, db_session: Session
) -> bool:
    # TODO: make this a check for None and add behavior for 0 day TTL
    if not retention_limit_days:
        return False

    task_name = name_chat_ttl_task(retention_limit_days)
    latest_task = get_latest_task(task_name, db_session)
    if not latest_task:
        return True

    if check_task_is_live_and_not_timed_out(latest_task, db_session):
        logger.debug(f"{task_name} is already being performed. Skipping.")
        return False
    return True
