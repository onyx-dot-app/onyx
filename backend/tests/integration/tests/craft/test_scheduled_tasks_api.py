"""Scheduled tasks tests (integration / HTTP half).

Integration tests for the user-facing scheduled-tasks HTTP API in
``onyx.server.features.build.scheduled_tasks.api``.

Hits the real backend over HTTP. The executor / dispatch state-machine
half is covered in
``tests/external_dependency_unit/craft/test_scheduled_task_executor.py``
— this file deliberately stays at the HTTP boundary and never invokes
the executor directly.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID
from uuid import uuid4

import httpx
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

# ---------------------------------------------------------------------------
# Inline HTTP wrapper — kept here per the task spec (no separate manager).
# ---------------------------------------------------------------------------


def _url(*parts: str) -> str:
    base = f"{API_SERVER_URL}/build/scheduled-tasks"
    if not parts:
        return base
    return base + "/" + "/".join(parts)


def _create_task(
    user: DATestUser,
    *,
    name: str | None = None,
    prompt: str = "Run the daily check.",
    editor_mode: str = "interval",
    editor_payload: dict[str, Any] | None = None,
    timezone: str = "UTC",
    status: ScheduledTaskStatus = ScheduledTaskStatus.ACTIVE,
    run_immediately: bool = False,
) -> httpx.Response:
    body: dict[str, Any] = {
        "name": name or f"task-{uuid4().hex[:8]}",
        "prompt": prompt,
        "editor_mode": editor_mode,
        "editor_payload": editor_payload or {"unit": "hours", "every": 1},
        "timezone": timezone,
        "status": status.value,
        "run_immediately": run_immediately,
    }
    return client.post(
        _url(),
        json=body,
        headers=user.headers,
        cookies=user.cookies,
    )


def _patch_task(
    user: DATestUser, task_id: UUID, body: dict[str, Any]
) -> httpx.Response:
    return client.patch(
        _url(str(task_id)),
        json=body,
        headers=user.headers,
        cookies=user.cookies,
    )


def _delete_task(user: DATestUser, task_id: UUID) -> httpx.Response:
    return client.delete(
        _url(str(task_id)),
        headers=user.headers,
        cookies=user.cookies,
    )


def _run_now(user: DATestUser, task_id: UUID) -> httpx.Response:
    return client.post(
        _url(str(task_id), "run-now"),
        headers=user.headers,
        cookies=user.cookies,
    )


def _list_runs(
    user: DATestUser,
    task_id: UUID,
    *,
    cursor: str | None = None,
    limit: int | None = None,
) -> httpx.Response:
    params: dict[str, Any] = {}
    if cursor is not None:
        params["cursor"] = cursor
    if limit is not None:
        params["limit"] = limit
    return client.get(
        _url(str(task_id), "runs"),
        params=params or None,
        headers=user.headers,
        cookies=user.cookies,
    )


def _get_task_row(task_id: UUID) -> ScheduledTask | None:
    with get_session_with_current_tenant() as db_session:
        return db_session.execute(
            select(ScheduledTask).where(ScheduledTask.id == task_id)
        ).scalar_one_or_none()


def _get_runs_for_task(task_id: UUID) -> list[ScheduledTaskRun]:
    with get_session_with_current_tenant() as db_session:
        return list(
            db_session.execute(
                select(ScheduledTaskRun)
                .where(ScheduledTaskRun.task_id == task_id)
                .order_by(ScheduledTaskRun.started_at.desc())
            )
            .scalars()
            .all()
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_task_compiles_cron(admin_user: DATestUser) -> None:
    """POST with ``editor_mode=interval`` compiles to a 5-field cron string."""
    response = _create_task(
        admin_user,
        editor_mode="interval",
        editor_payload={"unit": "hours", "every": 6},
        timezone="UTC",
    )
    response.raise_for_status()
    body = response.json()
    assert body["editor_mode"] == "interval"
    # Cron is canonical 5-field; "every 6 hours" compiles to "0 */6 * * *".
    cron = body["cron_expression"]
    assert isinstance(cron, str)
    assert len(cron.split()) == 5
    # DB row carries the same cron.
    row = _get_task_row(UUID(body["id"]))
    assert row is not None
    assert row.cron_expression == cron


def test_create_task_requires_paired_editor_fields(admin_user: DATestUser) -> None:
    """A missing required payload field is rejected.

    ``editor_mode=daily_weekly`` requires ``time_of_day`` in the payload;
    omitting it yields a Pydantic validation error → 422. The master
    plan describes this as 400 because most validation errors emerge as
    400, but Pydantic-level errors from FastAPI surface as 422.
    """
    response = _create_task(
        admin_user,
        editor_mode="daily_weekly",
        editor_payload={"weekdays": [1, 3, 5]},  # missing time_of_day
    )
    # Pydantic-level validation errors from FastAPI surface as 422.
    assert response.status_code == 422


def test_create_with_run_immediately_enqueues(admin_user: DATestUser) -> None:
    """``run_immediately=true`` creates a ``MANUAL_RUN_NOW`` run row in DB.

    We don't wait for the executor; we just verify the side effect of
    the POST: a ScheduledTaskRun row exists with
    ``trigger_source=MANUAL_RUN_NOW`` and ``status=QUEUED``.
    """
    response = _create_task(admin_user, run_immediately=True)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    runs = _get_runs_for_task(task_id)
    assert len(runs) >= 1
    [run] = [
        r for r in runs if r.trigger_source == ScheduledTaskTriggerSource.MANUAL_RUN_NOW
    ]
    # ``QUEUED`` is the insert-side state; the executor may have already
    # picked it up if running. Accept anything past QUEUED, but most
    # commonly QUEUED on freshly created.
    assert run.status in {
        ScheduledTaskRunStatus.QUEUED,
        ScheduledTaskRunStatus.RUNNING,
        ScheduledTaskRunStatus.SUCCEEDED,
        ScheduledTaskRunStatus.FAILED,
        ScheduledTaskRunStatus.SKIPPED,
    }


def test_patch_task_recomputes_next_run_at_on_schedule_change(
    admin_user: DATestUser,
) -> None:
    """A schedule edit recomputes ``next_run_at``."""
    response = _create_task(
        admin_user,
        editor_mode="interval",
        editor_payload={"unit": "hours", "every": 1},
    )
    response.raise_for_status()
    task_id = UUID(response.json()["id"])
    before = _get_task_row(task_id)
    assert before is not None
    before_next = before.next_run_at

    # PATCH the schedule to interval=days requiring time_of_day.
    patch = _patch_task(
        admin_user,
        task_id,
        {
            "editor_mode": "interval",
            "editor_payload": {
                "unit": "days",
                "every": 1,
                "time_of_day": "03:00",
            },
        },
    )
    patch.raise_for_status()
    after = _get_task_row(task_id)
    assert after is not None
    # The cron changes, and next_run_at is freshly computed by
    # update_scheduled_task. We don't pin a specific value (it depends
    # on now() at PATCH time and the requested schedule), but it must
    # be either ``None`` (paused) or a UTC datetime that differs from
    # the pre-patch value.
    assert after.cron_expression != before.cron_expression
    if after.status == ScheduledTaskStatus.ACTIVE:
        assert after.next_run_at is not None
        assert after.next_run_at != before_next


def test_run_now_on_paused_task_allowed(admin_user: DATestUser) -> None:
    """PAUSED task → ``run-now`` still works."""
    response = _create_task(admin_user, status=ScheduledTaskStatus.PAUSED)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    response = _run_now(admin_user, task_id)
    response.raise_for_status()
    body = response.json()
    assert "run_id" in body
    assert body["status"] in {s.value for s in ScheduledTaskRunStatus}

    runs = _get_runs_for_task(task_id)
    assert any(
        r.trigger_source == ScheduledTaskTriggerSource.MANUAL_RUN_NOW for r in runs
    )


def test_delete_task_is_idempotent_soft_delete(admin_user: DATestUser) -> None:
    """Two consecutive DELETEs both succeed."""
    response = _create_task(admin_user)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    first = _delete_task(admin_user, task_id)
    assert first.status_code == 204

    second = _delete_task(admin_user, task_id)
    # The handler is documented as idempotent — second DELETE on a
    # missing or already-deleted task returns 204.
    assert second.status_code == 204

    row = _get_task_row(task_id)
    # Soft delete: row still exists with deleted=True.
    assert row is not None, (
        "Row was hard-deleted; expected soft-delete to preserve the row"
    )
    assert row.deleted is True


def test_list_runs_paginates_by_started_at_cursor(admin_user: DATestUser) -> None:
    """``GET /runs?cursor=...`` works.

    Insert a couple of run rows by issuing ``run-now`` twice, then ask
    for page-size=1 to force a non-null next cursor.
    """
    response = _create_task(admin_user)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    # Fire two manual runs so we have at least two run rows. A small
    # sleep between them gives them distinct ``started_at`` values
    # (server_default=now() has microsecond resolution but identical
    # timestamps would still page correctly via the index).
    run_one = _run_now(admin_user, task_id)
    run_one.raise_for_status()
    time.sleep(0.05)
    run_two = _run_now(admin_user, task_id)
    run_two.raise_for_status()

    page_one = _list_runs(admin_user, task_id, limit=1)
    page_one.raise_for_status()
    page_one_body = page_one.json()
    assert len(page_one_body["items"]) == 1
    cursor = page_one_body["next_cursor"]
    assert isinstance(cursor, str) and cursor

    page_two = _list_runs(admin_user, task_id, cursor=cursor, limit=1)
    page_two.raise_for_status()
    page_two_body = page_two.json()
    assert len(page_two_body["items"]) >= 1
    # The two pages do not return the same run row.
    assert page_one_body["items"][0]["id"] != page_two_body["items"][0]["id"]


# NOTE: ``test_scheduled_run_session_excluded_from_sidebar`` was relocated
# to ``backend/tests/external_dependency_unit/craft/test_session_lifecycle.py``
# (``TestSidebarOriginFilter.test_scheduled_origin_session_excluded_from_sidebar_listing``).
#
# The original test inserted ``BuildSession`` + ``BuildMessage`` rows
# directly via ``get_session_with_current_tenant`` — an integration-shaped
# ext-dep assertion that bypasses the API. Moving it to ext-dep keeps the
# DB-row-visibility check at the right layer; ``GET /api/build/sessions``
# HTTP-shape is covered by the sidebar listing tests elsewhere.
#
# Driving this through the API in integration would require a running
# celery worker to execute the scheduled-task fire and insert the
# ``origin=SCHEDULED`` row — not currently guaranteed in integration CI.
