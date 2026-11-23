"""Run one scheduled-task run as a chat turn of its owner, with nobody watching.

The run's chat response decides the run status (`sync_chat_run__no_commit`).
A response that waits for approval parks; the owner's approval resumes it on
an API server, and the dispatcher brings the run status up to date.
"""

from datetime import datetime, timezone
from uuid import UUID

from onyx.auth.permissions import has_global_permission
from onyx.chat.process_message import run_chat_turn
from onyx.configs.constants import DEFAULT_PERSONA_ID, NotificationType
from onyx.db.chat import create_chat_session__no_commit
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    Permission,
    ScheduledTaskErrorClass,
    ScheduledTaskRunStatus,
)
from onyx.db.models import User
from onyx.db.scheduled_task import (
    ERROR_DETAIL_MAX_CHARS,
    get_run,
    mark_run_status,
    notify_run_owner__no_commit,
    sync_chat_run__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import ApprovalMode
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_USER_ID_CONTEXTVAR

logger = setup_logger()


def run_scheduled_task_logic(run_id: UUID) -> None:
    """Never raises: a Celery retry would run the prompt and its side effects
    twice. Every failure ends as a FAILED run."""
    try:
        started = _start_run(run_id)
        if started is None:
            return
        user, chat_session_id, prompt = started
        token = CURRENT_USER_ID_CONTEXTVAR.set(str(user.id))
        try:
            run_chat_turn(
                new_msg_req=SendMessageRequest(
                    message=prompt, chat_session_id=chat_session_id
                ),
                user=user,
                approval_mode=ApprovalMode.INTERACTIVE,
            )
        finally:
            CURRENT_USER_ID_CONTEXTVAR.reset(token)
        with get_session_with_current_tenant() as db_session:
            sync_chat_run__no_commit(
                db_session, get_run(db_session=db_session, run_id=run_id)
            )
            db_session.commit()
    except Exception as error:
        logger.exception("Scheduled task run %s failed", run_id)
        _fail(run_id, error)


def _start_run(run_id: UUID) -> tuple[User, UUID, str] | None:
    """Move a QUEUED run to RUNNING in a new hidden chat. None: nothing to run."""
    with get_session_with_current_tenant() as db_session:
        # Celery can deliver a message twice; the lock makes one delivery win.
        run = get_run(db_session=db_session, run_id=run_id, for_update=True)
        if run.status != ScheduledTaskRunStatus.QUEUED:
            return None
        task = run.task
        user = task.user
        # The checks of a chat send: an owner who can no longer chat, or who
        # is over budget, fails the run before its chat exists.
        if not user.is_active or not has_global_permission(user, Permission.WRITE_CHAT):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "The task owner can no longer chat",
            )
        check_token_rate_limits(user)
        # The chat and the RUNNING status commit together, under the run lock.
        chat_session = create_chat_session__no_commit(
            db_session,
            description=task.name,
            user_id=user.id,
            persona_id=DEFAULT_PERSONA_ID,
        )
        mark_run_status(
            db_session=db_session,
            run_id=run_id,
            status=ScheduledTaskRunStatus.RUNNING,
            chat_session_id=chat_session.id,
            started_at=datetime.now(tz=timezone.utc),
        )
        db_session.commit()
        return user, chat_session.id, task.prompt


def _fail(run_id: UUID, error: Exception) -> None:
    try:
        with get_session_with_current_tenant() as db_session:
            run = get_run(db_session=db_session, run_id=run_id)
            if run.status.is_terminal():
                return
            mark_run_status(
                db_session=db_session,
                run_id=run_id,
                status=ScheduledTaskRunStatus.FAILED,
                error_class=ScheduledTaskErrorClass.AGENT_EXCEPTION,
                error_detail=f"{type(error).__name__}: {error}"[
                    :ERROR_DETAIL_MAX_CHARS
                ],
            )
            notify_run_owner__no_commit(
                db_session, run, NotificationType.SCHEDULED_TASK_FAILED
            )
            db_session.commit()
    except Exception:
        logger.exception("Could not record the failure of scheduled run %s", run_id)
