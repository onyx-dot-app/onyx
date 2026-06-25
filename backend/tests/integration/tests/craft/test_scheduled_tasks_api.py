"""Scheduled tasks tests (HTTP contract)."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import ScheduledTaskRunStatus
from onyx.db.enums import ScheduledTaskStatus
from onyx.db.enums import ScheduledTaskTriggerSource
from onyx.db.models import ScheduledTask
from onyx.db.models import ScheduledTaskRun
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


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
    status: ScheduledTaskStatus = ScheduledTaskStatus.ACTIVE,
    run_immediately: bool = False,
) -> httpx.Response:
    body: dict[str, Any] = {
        "name": name or f"task-{uuid4().hex[:8]}",
        "prompt": prompt,
        "editor_mode": editor_mode,
        "editor_payload": editor_payload or {"unit": "hours", "every": 1},
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


def test_create_task_compiles_cron(admin_user: DATestUser) -> None:
    response = _create_task(
        admin_user,
        editor_mode="interval",
        editor_payload={"unit": "hours", "every": 6},
    )
    response.raise_for_status()
    body = response.json()
    assert body["editor_mode"] == "interval"
    cron = body["cron_expression"]
    assert isinstance(cron, str)
    assert len(cron.split()) == 5
    row = _get_task_row(UUID(body["id"]))
    assert row is not None
    assert row.cron_expression == cron


def test_create_task_interval_days_requires_time_of_day(admin_user: DATestUser) -> None:
    response = _create_task(
        admin_user,
        editor_mode="interval",
        editor_payload={"unit": "days", "every": 1},
    )
    assert response.status_code == 422


def test_create_with_run_immediately_enqueues(admin_user: DATestUser) -> None:
    response = _create_task(admin_user, run_immediately=True)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    runs = _get_runs_for_task(task_id)
    assert len(runs) >= 1
    [run] = [
        r for r in runs if r.trigger_source == ScheduledTaskTriggerSource.MANUAL_RUN_NOW
    ]
    # Executor may have advanced the run past QUEUED already.
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
    assert after.cron_expression != before.cron_expression
    if after.status == ScheduledTaskStatus.ACTIVE:
        assert after.next_run_at is not None
        assert after.next_run_at != before_next


def test_run_now_on_paused_task_allowed(admin_user: DATestUser) -> None:
    response = _create_task(admin_user, status=ScheduledTaskStatus.PAUSED)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    response = _run_now(admin_user, task_id)
    response.raise_for_status()
    body = response.json()
    assert "run_id" in body
    assert body["status"] == ScheduledTaskRunStatus.QUEUED.value

    runs = _get_runs_for_task(task_id)
    assert any(
        r.trigger_source == ScheduledTaskTriggerSource.MANUAL_RUN_NOW for r in runs
    )


def test_delete_task_is_idempotent_soft_delete(admin_user: DATestUser) -> None:
    response = _create_task(admin_user)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    first = _delete_task(admin_user, task_id)
    assert first.status_code == 204

    second = _delete_task(admin_user, task_id)
    assert second.status_code == 204

    row = _get_task_row(task_id)
    assert row is not None, (
        "Row was hard-deleted; expected soft-delete to preserve the row"
    )
    assert row.deleted is True


def test_list_runs_paginates_by_started_at_cursor(admin_user: DATestUser) -> None:
    response = _create_task(admin_user)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    # Small sleep gives the two runs distinct started_at values for the cursor.
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
    assert page_one_body["items"][0]["id"] != page_two_body["items"][0]["id"]
