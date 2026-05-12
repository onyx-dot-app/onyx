"""External-dependency unit tests for the Scheduled Tasks HTTP API.

We invoke the FastAPI route functions directly with a constructed ``User``
and the test ``db_session``, mirroring the pattern used in
``permission_sync/test_cc_pair_sync_attempts_routes.py``. The Celery
enqueue is patched at the ``api`` module's import site so no worker is
actually contacted.

Covers:
    * Happy-path CRUD on tasks (create / list / get / patch / soft-delete).
    * ``run_immediately`` and ``run-now`` insert a ``QUEUED`` run row and
      enqueue the executor with the expected args.
    * ``run-now`` works on PAUSED tasks and leaves ``next_run_at``
      untouched.
    * Schedule edits (timezone, status flips) drive the expected
      ``next_run_at`` recomputation.
    * Pagination of the runs listing, including ``next_cursor`` handoff.
    * Ownership boundary on ``/runs`` (other-user task → NOT_FOUND).
    * Session-view banner: 200 for a session linked to a run the caller
      owns, NOT_FOUND otherwise.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import BuildSession
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from onyx.db.models import User
from onyx.db.scheduled_task import insert_run
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.api.sessions_api import (
    get_session_scheduled_run_context,
)
from onyx.server.features.build.scheduled_tasks.api import create_task
from onyx.server.features.build.scheduled_tasks.api import delete_task
from onyx.server.features.build.scheduled_tasks.api import get_task
from onyx.server.features.build.scheduled_tasks.api import list_scheduled_tasks
from onyx.server.features.build.scheduled_tasks.api import list_task_runs
from onyx.server.features.build.scheduled_tasks.api import patch_task
from onyx.server.features.build.scheduled_tasks.api import run_now
from onyx.server.features.build.scheduled_tasks.api import RUNS_DEFAULT_PAGE_SIZE
from onyx.server.features.build.scheduled_tasks.api import ScheduledTaskCreate
from onyx.server.features.build.scheduled_tasks.api import ScheduledTaskPatch
from tests.external_dependency_unit.conftest import create_test_user

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _interval_payload(every: int = 5) -> dict[str, Any]:
    """Build a minimal interval-mode editor payload."""
    return {"every": every, "unit": "minutes"}


def _daily_weekly_payload(hour: int = 9, minute: int = 0) -> dict[str, Any]:
    """Build a minimal daily-weekly editor payload (every day at H:M)."""
    return {"hour": hour, "minute": minute, "weekdays": []}


@pytest.fixture
def mock_send_task(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the Celery enqueue used by the API.

    The router imports ``app as celery_app`` at module load, so we replace
    its ``send_task`` attribute. Tests can then assert on the recorded
    calls without spinning up Redis / a worker.
    """
    mock = MagicMock(name="celery_app.send_task")
    monkeypatch.setattr(
        "onyx.server.features.build.scheduled_tasks.api.celery_app.send_task",
        mock,
    )
    return mock


@pytest.fixture
def task_user(db_session: Session, tenant_context: None) -> User:  # noqa: ARG001
    """A standalone user for task ownership tests.

    We don't reuse the ``test_user`` fixture from the craft conftest
    because some tests need TWO distinct users (ownership boundary).
    """
    return create_test_user(db_session, "sched_task_user")


@pytest.fixture
def other_user(db_session: Session, tenant_context: None) -> User:  # noqa: ARG001
    """A second user used for cross-user permission tests."""
    return create_test_user(db_session, "sched_task_other")


# --------------------------------------------------------------------------- #
# Create / list / get / patch / delete
# --------------------------------------------------------------------------- #


class TestCRUDHappyPath:
    """Walk a single task through every CRUD endpoint."""

    def test_full_crud_lifecycle(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002 — unused but ensures no accidental enqueue
    ) -> None:
        # ---- Create ----
        create_req = ScheduledTaskCreate(
            name="Morning summary",
            prompt="Summarize my email and Slack threads",
            editor_mode="daily_weekly",
            editor_payload=_daily_weekly_payload(hour=9, minute=0),
            timezone="America/Los_Angeles",
        )
        created = create_task(request=create_req, user=task_user, db_session=db_session)
        assert created.name == "Morning summary"
        assert created.cron_expression == "0 9 * * *"
        assert created.timezone == "America/Los_Angeles"
        assert created.status == ScheduledTaskStatus.ACTIVE
        # Active task -> next_run_at populated, next_runs preview filled.
        assert created.next_run_at is not None
        assert len(created.next_runs) == 3
        assert created.last_run is None

        task_id = created.id
        # Confirm no enqueue happened (run_immediately defaulted to False).
        mock_send_task.assert_not_called()

        # ---- List ----
        listing = list_scheduled_tasks(user=task_user, db_session=db_session)
        assert len(listing.items) == 1
        assert listing.items[0].id == task_id
        assert listing.items[0].last_run is None

        # ---- Get ----
        from uuid import UUID

        detail = get_task(task_id=UUID(task_id), user=task_user, db_session=db_session)
        assert detail.id == task_id

        # ---- Patch (rename + timezone change) ----
        patched = patch_task(
            task_id=UUID(task_id),
            request=ScheduledTaskPatch(
                name="Morning summary v2", timezone="Europe/London"
            ),
            user=task_user,
            db_session=db_session,
        )
        assert patched.name == "Morning summary v2"
        assert patched.timezone == "Europe/London"
        # next_run_at should be recomputed because the timezone changed.
        assert patched.next_run_at is not None
        assert patched.next_run_at != created.next_run_at

        # ---- Delete (soft) ----
        resp = delete_task(task_id=UUID(task_id), user=task_user, db_session=db_session)
        assert resp.status_code == 204

        # ---- Subsequent list returns empty ----
        listing_after = list_scheduled_tasks(user=task_user, db_session=db_session)
        assert listing_after.items == []

        # ---- Get on deleted task -> NOT_FOUND ----
        with pytest.raises(OnyxError) as excinfo:
            get_task(task_id=UUID(task_id), user=task_user, db_session=db_session)
        assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND


# --------------------------------------------------------------------------- #
# run_immediately + run-now
# --------------------------------------------------------------------------- #


class TestRunImmediatelyAndRunNow:
    """Verify the two ways to fire a one-off execution."""

    def test_create_with_run_immediately_inserts_run_and_enqueues(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,
    ) -> None:
        created = create_task(
            request=ScheduledTaskCreate(
                name="Immediate",
                prompt="Run this once on save",
                editor_mode="interval",
                editor_payload=_interval_payload(every=15),
                timezone="UTC",
                run_immediately=True,
            ),
            user=task_user,
            db_session=db_session,
        )

        # A run row should now exist for this task.
        runs = (
            db_session.query(ScheduledTaskRun)
            .filter(ScheduledTaskRun.task_id == _uuid(created.id))
            .all()
        )
        assert len(runs) == 1
        run = runs[0]
        assert run.task_id == _uuid(created.id)
        assert run.status == ScheduledTaskRunStatus.QUEUED
        assert run.trigger_source == ScheduledTaskTriggerSource.MANUAL_RUN_NOW

        # And the executor should have been enqueued exactly once with the
        # right shape.
        mock_send_task.assert_called_once()
        call = mock_send_task.call_args
        assert (
            call.args[0] == "scheduled_tasks_run"
        )  # OnyxCeleryTask.SCHEDULED_TASKS_RUN
        assert call.kwargs["kwargs"] == {"run_id": str(run.id)}
        assert call.kwargs["queue"] == "scheduled_tasks"
        assert call.kwargs["expires"] == 900

    def test_run_now_on_paused_task_inserts_run_and_does_not_touch_next_run_at(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,
    ) -> None:
        created = create_task(
            request=ScheduledTaskCreate(
                name="Paused starter",
                prompt="Run on demand",
                editor_mode="interval",
                editor_payload=_interval_payload(every=30),
                timezone="UTC",
                status=ScheduledTaskStatus.PAUSED,
            ),
            user=task_user,
            db_session=db_session,
        )
        # Paused tasks have next_run_at == NULL.
        assert created.next_run_at is None
        assert created.status == ScheduledTaskStatus.PAUSED
        mock_send_task.assert_not_called()

        # Run Now should work on a paused task.
        run_resp = run_now(
            task_id=_uuid(created.id), user=task_user, db_session=db_session
        )
        assert run_resp.status == ScheduledTaskRunStatus.QUEUED

        # Run row exists with the right trigger.
        run = (
            db_session.query(ScheduledTaskRun)
            .filter(ScheduledTaskRun.id == _uuid(run_resp.run_id))
            .one()
        )
        assert run.trigger_source == ScheduledTaskTriggerSource.MANUAL_RUN_NOW

        # Task remains paused with next_run_at still NULL.
        task = (
            db_session.query(ScheduledTask)
            .filter(ScheduledTask.id == _uuid(created.id))
            .one()
        )
        assert task.status == ScheduledTaskStatus.PAUSED
        assert task.next_run_at is None

        mock_send_task.assert_called_once()


# --------------------------------------------------------------------------- #
# Patch: timezone + status transitions drive next_run_at
# --------------------------------------------------------------------------- #


class TestPatchRecomputesNextRunAt:
    """``update_scheduled_task`` recomputes ``next_run_at`` correctly."""

    def test_timezone_change_recomputes_next_run_at(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002
    ) -> None:
        created = create_task(
            request=ScheduledTaskCreate(
                name="TZ test",
                prompt="Test timezone changes",
                editor_mode="daily_weekly",
                editor_payload=_daily_weekly_payload(hour=9, minute=0),
                timezone="America/Los_Angeles",
            ),
            user=task_user,
            db_session=db_session,
        )
        original_next_run_at = created.next_run_at
        assert original_next_run_at is not None

        # Patch to a much earlier zone — 9 AM Tokyo is well before 9 AM LA.
        patched = patch_task(
            task_id=_uuid(created.id),
            request=ScheduledTaskPatch(timezone="Asia/Tokyo"),
            user=task_user,
            db_session=db_session,
        )
        assert patched.timezone == "Asia/Tokyo"
        assert patched.next_run_at is not None
        # In UTC, 9 AM Tokyo is much earlier than 9 AM LA on the same wall day.
        assert patched.next_run_at != original_next_run_at

    def test_status_paused_clears_next_run_at_and_resume_recomputes(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002
    ) -> None:
        created = create_task(
            request=ScheduledTaskCreate(
                name="Toggle pause",
                prompt="x",
                editor_mode="interval",
                editor_payload=_interval_payload(every=10),
                timezone="UTC",
            ),
            user=task_user,
            db_session=db_session,
        )
        assert created.next_run_at is not None

        # Pause.
        paused = patch_task(
            task_id=_uuid(created.id),
            request=ScheduledTaskPatch(status=ScheduledTaskStatus.PAUSED),
            user=task_user,
            db_session=db_session,
        )
        assert paused.status == ScheduledTaskStatus.PAUSED
        assert paused.next_run_at is None
        # next_runs should be [] when paused (UI shouldn't preview future
        # fires for a paused task).
        assert paused.next_runs == []

        # Resume.
        resumed = patch_task(
            task_id=_uuid(created.id),
            request=ScheduledTaskPatch(status=ScheduledTaskStatus.ACTIVE),
            user=task_user,
            db_session=db_session,
        )
        assert resumed.status == ScheduledTaskStatus.ACTIVE
        assert resumed.next_run_at is not None
        assert resumed.next_runs  # at least one preview fire


# --------------------------------------------------------------------------- #
# Run history pagination + ownership
# --------------------------------------------------------------------------- #


class TestListRuns:
    def test_pagination_60_runs(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002
    ) -> None:
        created = create_task(
            request=ScheduledTaskCreate(
                name="Pagination",
                prompt="x",
                editor_mode="interval",
                editor_payload=_interval_payload(every=5),
                timezone="UTC",
            ),
            user=task_user,
            db_session=db_session,
        )
        task_id = _uuid(created.id)

        # Insert 60 runs, each with a slightly different started_at so the
        # ordering by started_at DESC is unambiguous. We bypass the API
        # helper and rewrite started_at directly so we control ordering.
        base = datetime.now(tz=timezone.utc) - timedelta(hours=10)
        run_ids: list[str] = []
        for i in range(60):
            run = insert_run(
                db_session=db_session,
                task_id=task_id,
                trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
            )
            # Older index -> older started_at, so newest-first paging sees
            # i=59 first.
            run.started_at = base + timedelta(seconds=i)
            run_ids.append(str(run.id))
        db_session.commit()

        # Page 1.
        page1 = list_task_runs(
            task_id=task_id,
            cursor=None,
            limit=RUNS_DEFAULT_PAGE_SIZE,
            user=task_user,
            db_session=db_session,
        )
        assert len(page1.items) == 50
        # Newest first: the last-inserted run (i=59) should lead.
        assert page1.items[0].id == run_ids[59]
        assert page1.next_cursor is not None

        # Page 2 picks up the remaining 10.
        page2 = list_task_runs(
            task_id=task_id,
            cursor=page1.next_cursor,
            limit=RUNS_DEFAULT_PAGE_SIZE,
            user=task_user,
            db_session=db_session,
        )
        assert len(page2.items) == 10
        # The 50th run from the top of the full ordering -> i=9 in our
        # base-ascending insertion.
        assert page2.items[0].id == run_ids[9]
        assert page2.next_cursor is None

        # No overlap between the two pages.
        page1_ids = {item.id for item in page1.items}
        page2_ids = {item.id for item in page2.items}
        assert page1_ids.isdisjoint(page2_ids)

    def test_other_users_task_returns_not_found(
        self,
        db_session: Session,
        task_user: User,
        other_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002
    ) -> None:
        created = create_task(
            request=ScheduledTaskCreate(
                name="Ownership",
                prompt="x",
                editor_mode="interval",
                editor_payload=_interval_payload(every=5),
                timezone="UTC",
            ),
            user=task_user,
            db_session=db_session,
        )
        with pytest.raises(OnyxError) as excinfo:
            list_task_runs(
                task_id=_uuid(created.id),
                cursor=None,
                limit=RUNS_DEFAULT_PAGE_SIZE,
                user=other_user,
                db_session=db_session,
            )
        assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND


# --------------------------------------------------------------------------- #
# Scheduled-run-context banner
# --------------------------------------------------------------------------- #


class TestScheduledRunContext:
    """The session-view banner endpoint behaves correctly across ownership
    boundaries.
    """

    def test_returns_context_when_session_linked_to_owned_run(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002
    ) -> None:
        # Make a task + a run pointing at a fresh BuildSession.
        created = create_task(
            request=ScheduledTaskCreate(
                name="Banner test",
                prompt="x",
                editor_mode="interval",
                editor_payload=_interval_payload(every=5),
                timezone="UTC",
            ),
            user=task_user,
            db_session=db_session,
        )
        build_session = BuildSession(
            id=uuid4(),
            user_id=task_user.id,
            name="scheduled-run-session",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(build_session)
        db_session.flush()
        run = insert_run(
            db_session=db_session,
            task_id=_uuid(created.id),
            trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        )
        run.session_id = build_session.id
        db_session.commit()

        resp = get_session_scheduled_run_context(
            session_id=build_session.id,
            user=task_user,
            db_session=db_session,
        )
        assert resp.task_id == created.id
        assert resp.task_name == "Banner test"
        # started_at on the response matches the run row.
        assert resp.started_at == run.started_at

    def test_returns_not_found_for_unrelated_session(
        self,
        db_session: Session,
        task_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002
    ) -> None:
        # A session that has no scheduled-task run pointing at it.
        build_session = BuildSession(
            id=uuid4(),
            user_id=task_user.id,
            name="interactive-session",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(build_session)
        db_session.commit()

        with pytest.raises(OnyxError) as excinfo:
            get_session_scheduled_run_context(
                session_id=build_session.id,
                user=task_user,
                db_session=db_session,
            )
        assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND

    def test_returns_not_found_for_other_users_run(
        self,
        db_session: Session,
        task_user: User,
        other_user: User,
        mock_send_task: MagicMock,  # noqa: ARG002
    ) -> None:
        # task_user owns a scheduled run; other_user tries to view its
        # session and should get NOT_FOUND.
        created = create_task(
            request=ScheduledTaskCreate(
                name="Other user's task",
                prompt="x",
                editor_mode="interval",
                editor_payload=_interval_payload(every=5),
                timezone="UTC",
            ),
            user=task_user,
            db_session=db_session,
        )
        build_session = BuildSession(
            id=uuid4(),
            user_id=task_user.id,
            name="someone-elses-session",
            status=BuildSessionStatus.ACTIVE,
        )
        db_session.add(build_session)
        db_session.flush()
        run = insert_run(
            db_session=db_session,
            task_id=_uuid(created.id),
            trigger_source=ScheduledTaskTriggerSource.SCHEDULED,
        )
        run.session_id = build_session.id
        db_session.commit()

        with pytest.raises(OnyxError) as excinfo:
            get_session_scheduled_run_context(
                session_id=build_session.id,
                user=other_user,
                db_session=db_session,
            )
        assert excinfo.value.error_code is OnyxErrorCode.NOT_FOUND


# --------------------------------------------------------------------------- #
# Tiny helpers
# --------------------------------------------------------------------------- #


def _uuid(s: str) -> Any:
    """Cast a string id from a response model to a UUID for DB queries."""
    from uuid import UUID

    return UUID(s)
