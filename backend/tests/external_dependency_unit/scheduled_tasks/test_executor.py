"""Tests for the scheduled-task headless executor.

These tests stub `SessionManager._yield_acp_events` to deliver a
controlled stream of ACP events so the executor can be exercised
without provisioning a real sandbox or running an LLM.

What they verify:
- Happy path: QUEUED → RUNNING → SUCCEEDED, BuildSession has SCHEDULED
  origin, BuildMessage rows written via shared persistence consumer,
  summary populated, session_id set on the run.
- Approval gate: stream emits a `RequestPermissionRequest` → run ends
  in AWAITING_APPROVAL, sandbox lease released, notification emitted.
- Failure path: stream raises mid-iteration → run ends in FAILED,
  notification of type SCHEDULED_TASK_FAILED, lease released.
- Idempotency: pre-mark run as SUCCEEDED → executor no-ops.
"""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID

import pytest
from acp.schema import AgentMessageChunk
from acp.schema import PermissionOption
from acp.schema import RequestPermissionRequest
from acp.schema import TextContentBlock
from acp.schema import ToolCallUpdate
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.configs.constants import NotificationType
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.enums import SessionOrigin
from onyx.db.models import BuildMessage
from onyx.db.models import BuildSession
from onyx.db.models import Notification
from onyx.db.models import Sandbox
from onyx.db.models import ScheduledTask
from onyx.db.scheduled_task import get_run
from onyx.db.scheduled_task import insert_run
from onyx.server.features.build.scheduled_tasks.executor import run_scheduled_task_logic
from onyx.server.features.build.scheduled_tasks.sandbox_lease import is_sandbox_leased


def _make_chunk(text: str) -> AgentMessageChunk:
    """Build a minimal AgentMessageChunk ACP event."""
    return AgentMessageChunk.model_construct(
        content=TextContentBlock.model_construct(type="text", text=text),
        session_update="agent_message_chunk",
        session_id="placeholder",
    )


def _make_permission_request() -> RequestPermissionRequest:
    """Build a minimal `RequestPermissionRequest` ACP event."""
    return RequestPermissionRequest.model_construct(
        options=[
            PermissionOption.model_construct(
                kind="allow_once",
                name="Allow",
                option_id="allow",
            ),
        ],
        session_id="placeholder",
        tool_call=ToolCallUpdate.model_construct(tool_call_id="t1"),
    )


@pytest.fixture(autouse=True)
def _stub_sandbox_manager() -> Generator[MagicMock, None, None]:
    """Bypass `LocalSandboxManager._validate_templates` in unit tests.

    The real `get_sandbox_manager()` requires venv / outputs templates
    on disk; here we just need a stub that satisfies SessionManager's
    constructor.
    """
    with patch(
        "onyx.server.features.build.session.manager.get_sandbox_manager"
    ) as fake_get:
        fake_get.return_value = MagicMock()
        yield fake_get


@pytest.fixture(autouse=True)
def _stub_create_session() -> Generator[None, None, None]:
    """Replace `SessionManager.create_session__no_commit` with a thin DB insert.

    The real implementation provisions a sandbox, allocates ports, mkdirs
    document directories, etc. — none of which we need to exercise the
    executor's run-lifecycle logic. We just need a `BuildSession` row
    that lives in the same db_session and carries the requested origin.
    """
    from onyx.server.features.build.db.build_session import (
        create_build_session__no_commit,
    )
    from onyx.server.features.build.session.manager import SessionManager

    def fake_create(
        self: Any,
        user_id: Any,
        name: Any = None,
        user_work_area: Any = None,  # noqa: ARG001 — signature parity
        user_level: Any = None,  # noqa: ARG001
        llm_provider_type: Any = None,  # noqa: ARG001
        llm_model_name: Any = None,  # noqa: ARG001
        demo_data_enabled: bool = True,
        origin: Any = None,
    ) -> Any:
        from onyx.db.enums import SessionOrigin as _SessionOrigin

        return create_build_session__no_commit(
            user_id=user_id,
            db_session=self._db_session,
            name=name,
            demo_data_enabled=demo_data_enabled,
            origin=origin if origin is not None else _SessionOrigin.INTERACTIVE,
        )

    with patch.object(SessionManager, "create_session__no_commit", fake_create):
        yield


@pytest.fixture
def stub_acp_stream() -> Generator[Callable[[list[Any]], None], None, None]:
    """Patch SessionManager._yield_acp_events to yield the supplied events.

    Returns an installer the test calls with the list of events to emit
    (or with a single exception instance to raise mid-stream).
    """
    events_to_emit: dict[str, list[Any]] = {"events": []}

    def _yield_events_impl(
        self: Any,  # noqa: ARG001 — signature parity with patched method
        sandbox_id: Any,  # noqa: ARG001
        session_id: Any,  # noqa: ARG001
        user_message_content: str,  # noqa: ARG001
    ) -> Generator[Any, None, None]:
        for event in events_to_emit["events"]:
            if isinstance(event, BaseException):
                raise event
            yield event

    def _install(events: list[Any]) -> None:
        events_to_emit["events"] = events

    patcher = patch(
        "onyx.server.features.build.session.manager.SessionManager._yield_acp_events",
        _yield_events_impl,
    )
    patcher.start()
    try:
        yield _install
    finally:
        patcher.stop()


@pytest.fixture
def queued_run(
    db_session: Session,
    make_task: Callable[..., ScheduledTask],
    running_sandbox: Sandbox,  # noqa: ARG001 — implicit dependency
) -> tuple[ScheduledTask, UUID]:
    """Create a task + a freshly-inserted QUEUED run for it."""
    task = make_task(name="executor-test")
    run = insert_run(
        db_session=db_session,
        task_id=task.id,
        trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        status=ScheduledTaskRunStatus.QUEUED,
    )
    db_session.commit()
    return task, run.id


class TestExecutorHappyPath:
    def test_success_writes_messages_and_summary(
        self,
        db_session: Session,
        queued_run: tuple[ScheduledTask, UUID],
        running_sandbox: Sandbox,
        stub_acp_stream: Callable[[list[Any]], None],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """End-to-end: events drained, transcript persisted, summary set."""
        task, run_id = queued_run
        stub_acp_stream(
            [
                _make_chunk("Hello "),
                _make_chunk("from the agent."),
            ]
        )

        run_scheduled_task_logic(run_id)

        db_session.expire_all()
        run = get_run(db_session=db_session, run_id=run_id)
        assert run.status == ScheduledTaskRunStatus.SUCCEEDED
        assert run.session_id is not None
        assert run.summary is not None
        assert "Hello from the agent." in run.summary

        # BuildSession is SCHEDULED — verifies the executor wired origin
        # through correctly.
        session_row = db_session.get(BuildSession, run.session_id)
        assert session_row is not None
        assert session_row.origin == SessionOrigin.SCHEDULED

        # Messages: turn 0 user prompt + accumulated agent_message.
        messages = list(
            db_session.execute(
                select(BuildMessage)
                .where(BuildMessage.session_id == run.session_id)
                .order_by(BuildMessage.created_at)
            ).scalars()
        )
        assert len(messages) >= 2
        user_msgs = [m for m in messages if m.type == MessageType.USER]
        assistant_msgs = [m for m in messages if m.type == MessageType.ASSISTANT]
        assert len(user_msgs) == 1
        assert (
            user_msgs[0].message_metadata.get("content", {}).get("text") == task.prompt
        )
        # Accumulated agent_message: concatenated text.
        final_agent_text = "".join(
            (m.message_metadata or {}).get("content", {}).get("text", "")
            for m in assistant_msgs
            if (m.message_metadata or {}).get("type") == "agent_message"
        )
        assert "Hello from the agent." in final_agent_text

        # Lease released — sandbox available again.
        assert not is_sandbox_leased(running_sandbox.id)


class TestExecutorApprovalGate:
    def test_approval_required_releases_lease_and_marks_awaiting(
        self,
        db_session: Session,
        queued_run: tuple[ScheduledTask, UUID],
        running_sandbox: Sandbox,
        stub_acp_stream: Callable[[list[Any]], None],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        task, run_id = queued_run
        stub_acp_stream(
            [
                _make_chunk("Need permission for "),
                _make_permission_request(),
                # Anything after the approval gate should be ignored.
                _make_chunk("never seen"),
            ]
        )

        run_scheduled_task_logic(run_id)

        db_session.expire_all()
        run = get_run(db_session=db_session, run_id=run_id)
        assert run.status == ScheduledTaskRunStatus.AWAITING_APPROVAL
        assert run.session_id is not None

        # Lease was released early so the interactive UI can use the
        # sandbox while the run is paused.
        assert not is_sandbox_leased(running_sandbox.id)

        # AWAITING_APPROVAL notification was emitted.
        notifications = list(
            db_session.execute(
                select(Notification).where(
                    Notification.user_id == task.user_id,
                    Notification.notif_type
                    == NotificationType.SCHEDULED_TASK_AWAITING_APPROVAL,
                )
            ).scalars()
        )
        assert notifications, "Expected an awaiting-approval notification"


class TestExecutorFailure:
    def test_exception_marks_failed_and_notifies(
        self,
        db_session: Session,
        queued_run: tuple[ScheduledTask, UUID],
        running_sandbox: Sandbox,
        stub_acp_stream: Callable[[list[Any]], None],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        task, run_id = queued_run
        stub_acp_stream(
            [
                _make_chunk("Starting..."),
                RuntimeError("sandbox blew up mid-stream"),
            ]
        )

        run_scheduled_task_logic(run_id)

        db_session.expire_all()
        run = get_run(db_session=db_session, run_id=run_id)
        assert run.status == ScheduledTaskRunStatus.FAILED
        assert run.error_class == "RuntimeError"
        assert run.error_detail is not None
        assert "blew up" in run.error_detail

        # Lease released even on failure.
        assert not is_sandbox_leased(running_sandbox.id)

        notifications = list(
            db_session.execute(
                select(Notification).where(
                    Notification.user_id == task.user_id,
                    Notification.notif_type == NotificationType.SCHEDULED_TASK_FAILED,
                )
            ).scalars()
        )
        assert notifications, "Expected a failure notification"


class TestExecutorIdempotency:
    def test_already_terminal_run_is_noop(
        self,
        db_session: Session,
        queued_run: tuple[ScheduledTask, UUID],
        running_sandbox: Sandbox,  # noqa: ARG002
        stub_acp_stream: Callable[[list[Any]], None],
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        _, run_id = queued_run
        # Pre-mark the run terminal via direct ORM update.
        run = get_run(db_session=db_session, run_id=run_id)
        run.status = ScheduledTaskRunStatus.SUCCEEDED
        run.summary = "already done"
        db_session.commit()

        # Stream is a poison pill — if the executor runs, this would
        # raise and we'd see FAILED. The point is it shouldn't run.
        stub_acp_stream([RuntimeError("should not be invoked")])

        run_scheduled_task_logic(run_id)

        db_session.expire_all()
        run = get_run(db_session=db_session, run_id=run_id)
        assert run.status == ScheduledTaskRunStatus.SUCCEEDED
        assert run.summary == "already done"
