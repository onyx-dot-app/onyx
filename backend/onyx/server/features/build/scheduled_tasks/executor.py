"""Headless executor for Craft scheduled tasks.

The Celery `run_scheduled_task` task is a thin wrapper around
``run_scheduled_task_logic`` here. Splitting it out keeps the agent-drive
logic importable + testable without a Celery worker (external-dependency
unit tests instantiate it directly).

Lifecycle (see ``docs/craft/features/scheduled-tasks.md``):

1. Fetch the run row + owning task. Bail out idempotently if the run is
   not ``QUEUED`` (Celery may redeliver, or a sweeper may have already
   marked it failed).
2. Transition QUEUED -> RUNNING.
3. Create a fresh ``BuildSession`` with ``origin=SCHEDULED``. Record its
   id on the run row.
4. Drive the agent via the shared ``_yield_acp_events`` generator,
   persisting each event with ``_persist_acp_event``. Enforce a 30 min
   monotonic budget (Celery thread-pool time limits are silently
   disabled — see CLAUDE.md).
5. On ``RequestPermissionRequest`` (approval gate): mark
   ``AWAITING_APPROVAL``, emit a notification, return without writing a
   terminal status. Resume mechanics are owned by the approvals project;
   until that ships these runs are "terminal-for-display".
6. On clean stream completion: ``_finalize_persist``, derive a
   ~120-char summary, mark ``SUCCEEDED``.
7. On any exception inside the drive loop: mark ``FAILED`` with the
   exception class/detail and emit a notification. We deliberately
   swallow the exception so Celery doesn't retry (no retries in V1).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from acp.schema import RequestPermissionRequest

from onyx.configs.constants import MessageType
from onyx.configs.constants import NotificationType
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SandboxStatus
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import SessionOrigin
from onyx.db.notification import create_notification
from onyx.db.scheduled_task import get_run
from onyx.db.scheduled_task import mark_run_status
from onyx.server.features.build.db.build_session import create_message
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.session.manager import BuildStreamingState
from onyx.server.features.build.session.manager import SessionManager
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Per-run wall-clock budget (monotonic). Tasks that blow past this are
# marked ``failed (error_class=timeout)``. The stuck-run sweeper uses a
# slightly larger threshold (45 min) so a hung run that fails to honor the
# budget still gets cleaned up out-of-band.
DEFAULT_EXECUTOR_BUDGET_SECONDS = 30 * 60

# Summary length on the run row (per spec: ~120 chars of final agent
# message).
SUMMARY_MAX_CHARS = 120


def _summary_from_state(state: BuildStreamingState, fallback: str = "") -> str:
    """Build a ~120-char summary from accumulated agent message text.

    Prefers the in-memory ``state.message_chunks`` (the most recent
    streaming-only text). Falls back to ``fallback``.
    """
    if state.message_chunks:
        full = "".join(state.message_chunks).strip()
        if full:
            return full[:SUMMARY_MAX_CHARS]
    return fallback[:SUMMARY_MAX_CHARS] if fallback else ""


def _summary_from_session_messages(session_id: UUID, db_session: Any) -> str:
    """Fall back to scanning persisted messages for a summary.

    Walks the session's messages newest-first looking for the last
    ``agent_message`` metadata blob and trims it. Used when the in-memory
    BuildStreamingState has no remaining pending chunks (e.g. they were
    flushed mid-stream).
    """
    rows = get_session_messages(session_id=session_id, db_session=db_session)
    for msg in reversed(rows):
        meta = msg.message_metadata or {}
        if not isinstance(meta, dict):
            continue
        if meta.get("type") != "agent_message":
            continue
        content = meta.get("content") or {}
        if isinstance(content, dict):
            text = content.get("text") or ""
            if isinstance(text, str) and text.strip():
                return text.strip()[:SUMMARY_MAX_CHARS]
    return ""


def _notify(
    *,
    db_session: Any,
    user_id: UUID,
    task_name: str,
    task_id: UUID,
    run_id: UUID,
    notif_type: NotificationType,
) -> None:
    """Emit a per-user notification for failed / awaiting_approval runs.

    Failures are best-effort — never let a notification error mask the
    underlying run-status update.
    """
    title = (
        f'Scheduled task "{task_name}" failed'
        if notif_type == NotificationType.SCHEDULED_TASK_FAILED
        else f'Scheduled task "{task_name}" needs approval'
    )
    try:
        create_notification(
            user_id=user_id,
            notif_type=notif_type,
            db_session=db_session,
            title=title,
            additional_data={
                "task_id": str(task_id),
                "run_id": str(run_id),
            },
            autocommit=False,
        )
    except Exception:
        logger.exception(
            "Failed to create scheduled-task notification (user=%s task=%s run=%s)",
            user_id,
            task_id,
            run_id,
        )


def run_scheduled_task_logic(
    run_id: UUID,
    *,
    budget_seconds: int = DEFAULT_EXECUTOR_BUDGET_SECONDS,
) -> None:
    """Execute a single scheduled-task run end-to-end.

    Owns the run-status state machine for one run. Always returns
    cleanly — exceptions inside the agent drive are translated into a
    ``FAILED`` row + notification rather than re-raised, so Celery doesn't
    auto-retry (no retries in V1).

    Args:
        run_id: The ``ScheduledTaskRun.id`` to execute.
        budget_seconds: Per-run wall-clock budget. Defaults to 30 min.
            Exposed for tests.
    """
    # Phase 1: validate the run is still actionable; transition to RUNNING.
    # We commit aggressively here so the RUNNING transition is visible to
    # external observers (the UI, the stuck-run sweeper).
    with get_session_with_current_tenant() as db_session:
        try:
            run = get_run(db_session=db_session, run_id=run_id)
        except Exception:
            logger.warning("Scheduled run %s not found; nothing to do.", run_id)
            return

        if run.status != ScheduledTaskRunStatus.QUEUED:
            # Idempotent: a retry / sweeper / manual mark beat us here.
            logger.info(
                "Scheduled run %s is not QUEUED (status=%s); skipping.",
                run_id,
                run.status,
            )
            return

        # Resolve the task directly off the ORM relationship rather than
        # `get_scheduled_task` so a soft-deleted task (deleted between
        # dispatch and execution) can still complete the run that was
        # already queued — the V1 contract is that in-flight runs survive
        # a delete.
        task = run.task
        if task is None:
            mark_run_status(
                db_session=db_session,
                run_id=run_id,
                status=ScheduledTaskRunStatus.FAILED,
                error_class="task_missing",
                error_detail="Scheduled task row no longer exists",
            )
            db_session.commit()
            return
        task_id = task.id
        task_user_id = task.user_id
        task_name = task.name
        task_prompt = task.prompt

        sandbox = get_sandbox_by_user_id(db_session, task_user_id)
        if sandbox is None or sandbox.status != SandboxStatus.RUNNING:
            # No sandbox at all (user has never opened Craft) or it's
            # not running. Treat as transient — skip with a clear reason.
            mark_run_status(
                db_session=db_session,
                run_id=run_id,
                status=ScheduledTaskRunStatus.SKIPPED,
                skip_reason="sandbox_unavailable",
            )
            db_session.commit()
            logger.info(
                "Scheduled run %s skipped — sandbox unavailable for user %s",
                run_id,
                task_user_id,
            )
            return

        sandbox_id = sandbox.id

        mark_run_status(
            db_session=db_session,
            run_id=run_id,
            status=ScheduledTaskRunStatus.RUNNING,
        )
        db_session.commit()

    # Phase 2: drive the agent. We open a fresh session inside the drive
    # because the agent loop can be long-running and we don't want a
    # single open transaction for the duration. Multiple scheduled runs
    # can execute against the same sandbox concurrently — there is no
    # serialization with the interactive `send_message` path.
    try:
        _drive_agent(
            run_id=run_id,
            task_id=task_id,
            task_user_id=task_user_id,
            task_name=task_name,
            task_prompt=task_prompt,
            sandbox_id=sandbox_id,
            budget_seconds=budget_seconds,
        )
    except Exception:
        # Catch-all: anything that escapes the inner drive (e.g. session
        # creation failure). Translate to FAILED.
        logger.exception("Unexpected error executing scheduled run %s", run_id)
        with get_session_with_current_tenant() as db_session:
            try:
                run = get_run(db_session=db_session, run_id=run_id)
                if not run.status.is_terminal():
                    mark_run_status(
                        db_session=db_session,
                        run_id=run_id,
                        status=ScheduledTaskRunStatus.FAILED,
                        error_class="executor_error",
                        error_detail="Unexpected executor failure",
                    )
                    _notify(
                        db_session=db_session,
                        user_id=task_user_id,
                        task_name=task_name,
                        task_id=task_id,
                        run_id=run_id,
                        notif_type=NotificationType.SCHEDULED_TASK_FAILED,
                    )
                db_session.commit()
            except Exception:
                logger.exception(
                    "Double-failure marking scheduled run %s as failed", run_id
                )


def _drive_agent(
    *,
    run_id: UUID,
    task_id: UUID,
    task_user_id: UUID,
    task_name: str,
    task_prompt: str,
    sandbox_id: UUID,
    budget_seconds: int,
) -> bool:
    """Drive the agent for a single scheduled run.

    Creates the BuildSession, persists the user prompt, iterates ACP
    events with the shared persistence consumer, and writes the terminal
    run status.

    Returns:
        ``True`` if the run paused on an approval gate (run status is
        AWAITING_APPROVAL). ``False`` otherwise (run status is terminal).
    """
    # We open a single session for the whole drive so that the
    # `_persist_acp_event` calls (which write `BuildMessage` rows) and the
    # final `mark_run_status` happen against the same connection. The
    # session is committed eagerly at key points so observers see progress.
    with get_session_with_current_tenant() as db_session:
        session_manager = SessionManager(db_session)

        # Create the BuildSession. SCHEDULED origin keeps it out of the
        # Craft sidebar (see `get_user_build_sessions`).
        build_session = session_manager.create_session__no_commit(
            user_id=task_user_id,
            origin=SessionOrigin.SCHEDULED,
            name=f"Scheduled: {task_name}",
        )
        session_id = build_session.id

        # Persist the user prompt as turn 0 so the transcript matches an
        # interactive run exactly (interactive flow does the same in
        # `_stream_cli_agent_response`).
        create_message(
            session_id=session_id,
            message_type=MessageType.USER,
            turn_index=0,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": task_prompt},
            },
            db_session=db_session,
        )

        # Wire the session id onto the run row so the UI can deep-link
        # from the run history into the session view as soon as anything
        # is persisted.
        mark_run_status(
            db_session=db_session,
            run_id=run_id,
            status=ScheduledTaskRunStatus.RUNNING,
            session_id=session_id,
        )
        db_session.commit()

        state = BuildStreamingState(turn_index=0)
        deadline = time.monotonic() + budget_seconds

        approval_required = False
        final_event_count = 0
        try:
            for acp_event in session_manager._yield_acp_events(
                sandbox_id, session_id, task_prompt
            ):
                # Approval gate: mark awaiting_approval, return. Resume
                # mechanics are owned by the approvals project; this is
                # "terminal for display" until it ships.
                if isinstance(acp_event, RequestPermissionRequest):
                    approval_required = True
                    break

                # Budget check happens before persistence so a runaway
                # agent can't keep growing the transcript.
                if time.monotonic() > deadline:
                    session_manager._finalize_persist(session_id, state)
                    mark_run_status(
                        db_session=db_session,
                        run_id=run_id,
                        status=ScheduledTaskRunStatus.FAILED,
                        error_class="timeout",
                        error_detail=f"budget exceeded ({budget_seconds}s)",
                    )
                    _notify(
                        db_session=db_session,
                        user_id=task_user_id,
                        task_name=task_name,
                        task_id=task_id,
                        run_id=run_id,
                        notif_type=NotificationType.SCHEDULED_TASK_FAILED,
                    )
                    db_session.commit()
                    return False

                session_manager._persist_acp_event(session_id, state, acp_event)
                final_event_count += 1

            if approval_required:
                # Capture the summary BEFORE finalize_persist — the
                # finalize call clears `state.message_chunks` so we'd
                # always fall back to the persisted-message scan.
                summary_from_chunks = _summary_from_state(state)
                # Flush any pending chunks so the transcript reflects
                # what the agent has said before pausing.
                session_manager._finalize_persist(session_id, state)
                db_session.commit()
                summary = summary_from_chunks or _summary_from_session_messages(
                    session_id, db_session
                )
                mark_run_status(
                    db_session=db_session,
                    run_id=run_id,
                    status=ScheduledTaskRunStatus.AWAITING_APPROVAL,
                    summary=summary or None,
                )
                _notify(
                    db_session=db_session,
                    user_id=task_user_id,
                    task_name=task_name,
                    task_id=task_id,
                    run_id=run_id,
                    notif_type=NotificationType.SCHEDULED_TASK_AWAITING_APPROVAL,
                )
                db_session.commit()
                return True

            # Clean completion path.
            summary_from_chunks = _summary_from_state(state)
            session_manager._finalize_persist(session_id, state)
            db_session.commit()
            summary = summary_from_chunks or _summary_from_session_messages(
                session_id, db_session
            )
            mark_run_status(
                db_session=db_session,
                run_id=run_id,
                status=ScheduledTaskRunStatus.SUCCEEDED,
                summary=summary or None,
            )
            db_session.commit()
            logger.info(
                "Scheduled run %s succeeded (events=%d, session=%s)",
                run_id,
                final_event_count,
                session_id,
            )
            return False
        except Exception as exc:
            # Roll back any uncommitted persistence work and translate
            # to FAILED. Do NOT re-raise — Celery would retry, which is
            # explicitly out of scope for V1.
            db_session.rollback()
            error_class = type(exc).__name__
            error_detail = str(exc)[:1000] or error_class
            try:
                mark_run_status(
                    db_session=db_session,
                    run_id=run_id,
                    status=ScheduledTaskRunStatus.FAILED,
                    error_class=error_class,
                    error_detail=error_detail,
                )
                _notify(
                    db_session=db_session,
                    user_id=task_user_id,
                    task_name=task_name,
                    task_id=task_id,
                    run_id=run_id,
                    notif_type=NotificationType.SCHEDULED_TASK_FAILED,
                )
                db_session.commit()
            except Exception:
                logger.exception(
                    "Failed to mark scheduled run %s as FAILED after error",
                    run_id,
                )
            logger.exception("Scheduled run %s failed", run_id)
            return False


# Re-export for the Celery task wrapper.
__all__ = [
    "DEFAULT_EXECUTOR_BUDGET_SECONDS",
    "run_scheduled_task_logic",
]
