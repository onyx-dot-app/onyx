#####
# Periodic Tasks
#####
import json
from typing import Any

from celery import shared_task
from celery.contrib.abortable import AbortableTask  # type: ignore
from celery.exceptions import TaskRevokedError
from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.background.celery.apps.app_base import task_logger
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import PostgresAdvisoryLocks
from onyx.db.engine.sql_engine import get_session_with_current_tenant


@shared_task(
    name=OnyxCeleryTask.KOMBU_MESSAGE_CLEANUP_TASK,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
    base=AbortableTask,
)
def kombu_message_cleanup_task(self: Any, tenant_id: str) -> int:
    """Runs periodically to clean up the kombu_message table"""

    # we will select messages older than this amount to clean up
    KOMBU_MESSAGE_CLEANUP_AGE = 7  # days
    KOMBU_MESSAGE_CLEANUP_PAGE_LIMIT = 1000

    ctx = {}
    ctx["last_processed_id"] = 0
    ctx["deleted"] = 0
    ctx["cleanup_age"] = KOMBU_MESSAGE_CLEANUP_AGE
    ctx["page_limit"] = KOMBU_MESSAGE_CLEANUP_PAGE_LIMIT
    with get_session_with_current_tenant() as db_session:
        # Exit the task if we can't take the advisory lock
        result = db_session.execute(
            text("SELECT pg_try_advisory_lock(:id)"),
            {"id": PostgresAdvisoryLocks.KOMBU_MESSAGE_CLEANUP_LOCK_ID.value},
        ).scalar()
        if not result:
            return 0

        while True:
            if self.is_aborted():
                raise TaskRevokedError("kombu_message_cleanup_task was aborted.")

            b = kombu_message_cleanup_task_helper(ctx, db_session)
            if not b:
                break

            db_session.commit()

    if ctx["deleted"] > 0:
        task_logger.info(
            f"Deleted {ctx['deleted']} orphaned messages from kombu_message."
        )

    return ctx["deleted"]


def kombu_message_cleanup_task_helper(ctx: dict, db_session: Session) -> bool:
    """
    Helper function to clean up old messages from the `kombu_message` table that are no longer relevant.

    This function retrieves messages from the `kombu_message` table that are no longer visible and
    older than a specified interval. It checks if the corresponding task_id exists in the
    `celery_taskmeta` table. If the task_id does not exist, the message is deleted.

    Args:
        ctx (dict): A context dictionary containing configuration parameters such as:
            - 'cleanup_age' (int): The age in days after which messages are considered old.
            - 'page_limit' (int): The maximum number of messages to process in one batch.
            - 'last_processed_id' (int): The ID of the last processed message to handle pagination.
            - 'deleted' (int): A counter to track the number of deleted messages.
        db_session (Session): The SQLAlchemy database session for executing queries.

    Returns:
        bool: Returns True if there are more rows to process, False if not.
    """

    inspector = inspect(db_session.bind)
    if not inspector:
        return False

    # With the move to redis as celery's broker and backend, kombu tables may not even exist.
    # We can fail silently.
    if not inspector.has_table("kombu_message"):
        return False

    query = text(
        """
    SELECT id, timestamp, payload
    FROM kombu_message WHERE visible = 'false'
    AND timestamp < CURRENT_TIMESTAMP - INTERVAL :interval_days
    AND id > :last_processed_id
    ORDER BY id
    LIMIT :page_limit
"""
    )
    kombu_messages = db_session.execute(
        query,
        {
            "interval_days": f"{ctx['cleanup_age']} days",
            "page_limit": ctx["page_limit"],
            "last_processed_id": ctx["last_processed_id"],
        },
    ).fetchall()

    if len(kombu_messages) == 0:
        return False

    for msg in kombu_messages:
        payload = json.loads(msg[2])
        task_id = payload["headers"]["id"]

        # Check if task_id exists in celery_taskmeta
        task_exists = db_session.execute(
            text("SELECT 1 FROM celery_taskmeta WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).fetchone()

        # If task_id does not exist, delete the message
        if not task_exists:
            result = db_session.execute(
                text("DELETE FROM kombu_message WHERE id = :message_id"),
                {"message_id": msg[0]},
            )
            if result.rowcount > 0:  # type: ignore
                ctx["deleted"] += 1

        ctx["last_processed_id"] = msg[0]

    return True
