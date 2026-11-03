from celery import Celery

from onyx.utils.logger import setup_logger

logger = setup_logger()


def revoke_restarted_attempt_tasks(
    celery_app: Celery, celery_task_ids: list[str]
) -> None:
    """Revokes the docfetching tasks that request_attempt_restart__no_commit
    returned. Call it only after that restart commits: after a rollback, a
    revoked task would leave its attempt active with nothing to run it. A
    task already running is not interrupted; it stops on its next attempt
    status check."""
    for task_id in celery_task_ids:
        celery_app.control.revoke(task_id)
        logger.info("Revoked docfetching task for a restart: task_id=%s", task_id)
