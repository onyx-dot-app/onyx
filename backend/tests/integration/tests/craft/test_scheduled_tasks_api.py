"""Scheduled tasks tests (HTTP contract)."""

from __future__ import annotations

import time
from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import (
    PluginInstallationPolicy,
    ScheduledTaskRunStatus,
    ScheduledTaskStatus,
    ScheduledTaskTriggerSource,
)
from onyx.db.models import ScheduledTask, ScheduledTaskRun
from onyx.db.scheduled_task import insert_run, mark_run_status
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)
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
    integrations: list[dict[str, Any]] | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "name": name or f"task-{uuid4().hex[:8]}",
        "prompt": prompt,
        "editor_mode": editor_mode,
        "editor_payload": editor_payload or {"unit": "hours", "every": 1},
        "status": status.value,
        "run_immediately": run_immediately,
    }
    if integrations is not None:
        body["integrations"] = integrations
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
    unviewed: bool = False,
) -> httpx.Response:
    params: dict[str, Any] = {}
    if unviewed:
        params["unviewed"] = True
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


@pytest.fixture
def task_integration() -> Generator[int, None, None]:
    """An MCP integration with one action that each user has on."""
    with get_session_with_current_tenant() as db_session:
        integration, _ = make_mcp_integration(
            db_session,
            server_url=f"https://{uuid4().hex[:8]}.example.com/mcp",
            name=f"task-mcp-{uuid4().hex[:6]}",
            tools=("send_report",),
        )
        give_access(
            db_session,
            [integration],
            published=True,
            installation_policy=PluginInstallationPolicy.DEFAULT,
        )
        integration_id = integration.id
    try:
        yield integration_id
    finally:
        with get_session_with_current_tenant() as db_session:
            delete_integrations(db_session, [integration_id])


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


def test_create_and_patch_task_integrations(
    admin_user: DATestUser, task_integration: int
) -> None:
    link = {
        "integration_id": task_integration,
        "action_settings": {"default": "inherit", "actions": {"send_report": "allow"}},
    }
    response = _create_task(admin_user, integrations=[link])
    response.raise_for_status()
    task_id = UUID(response.json()["id"])
    assert response.json()["integrations"] == [link]

    response = client.get(
        _url(str(task_id), "action-policies"),
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    response.raise_for_status()
    view = next(row for row in response.json() if row["id"] == task_integration)
    assert view["enabled"] is True
    assert view["runnable"] is True
    assert view["action_settings"] == link["action_settings"]
    action = view["actions"][0]
    assert action["key"] == "send_report"
    assert action["integration_policy"] == "ask"
    assert action["locked"] is False

    response = _patch_task(admin_user, task_id, {"name": "Renamed"})
    response.raise_for_status()
    assert response.json()["integrations"] == [link]
    response = _patch_task(admin_user, task_id, {"integrations": []})
    response.raise_for_status()
    assert response.json()["integrations"] == []


def test_task_integrations_reject_unknown_integrations_and_actions(
    admin_user: DATestUser, task_integration: int
) -> None:
    unknown_action = {
        "integration_id": task_integration,
        "action_settings": {"actions": {"not_an_action": "allow"}},
    }
    assert _create_task(admin_user, integrations=[unknown_action]).status_code == 400
    unknown_integration = {"integration_id": -1, "action_settings": {}}
    assert (
        _create_task(admin_user, integrations=[unknown_integration]).status_code == 404
    )


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
                "time_of_day": "03:17",
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


def _insert_run_with_status(task_id: UUID, *statuses: ScheduledTaskRunStatus) -> UUID:
    with get_session_with_current_tenant() as db_session:
        run = insert_run(
            db_session=db_session,
            task_id=task_id,
            trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
        )
        for status in statuses:
            mark_run_status(db_session=db_session, run_id=run.id, status=status)
        db_session.commit()
        return run.id


def _set_run_status(run_id: UUID, status: ScheduledTaskRunStatus) -> None:
    with get_session_with_current_tenant() as db_session:
        mark_run_status(db_session=db_session, run_id=run_id, status=status)
        db_session.commit()


def _view_run(
    user: DATestUser, task_id: UUID, run_id: UUID, revision: int
) -> httpx.Response:
    return client.patch(
        _url(str(task_id), "runs", str(run_id), "viewed"),
        json={"revision": revision},
        headers=user.headers,
        cookies=user.cookies,
    )


def _unviewed_run_count(user: DATestUser, task_id: UUID) -> int:
    response = client.get(_url(), headers=user.headers, cookies=user.cookies)
    response.raise_for_status()
    item = next(i for i in response.json()["items"] if i["id"] == str(task_id))
    return item["unviewed_run_count"]


def test_run_results_stay_unviewed_until_opened(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    response = _create_task(admin_user, status=ScheduledTaskStatus.PAUSED)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    with get_session_with_current_tenant() as db_session:
        skipped_id = insert_run(
            db_session=db_session,
            task_id=task_id,
            trigger_source=ScheduledTaskTriggerSource.MANUAL_RUN_NOW,
            status=ScheduledTaskRunStatus.SKIPPED,
        ).id
        db_session.commit()
    run_id = _insert_run_with_status(
        task_id, ScheduledTaskRunStatus.RUNNING, ScheduledTaskRunStatus.SUCCEEDED
    )
    assert _unviewed_run_count(admin_user, task_id) == 1
    count = client.get(
        _url("unviewed-count"), headers=admin_user.headers, cookies=admin_user.cookies
    )
    count.raise_for_status()
    assert count.json()["count"] >= 1

    runs = {run["id"]: run for run in _list_runs(admin_user, task_id).json()["items"]}
    assert runs[str(run_id)]["revision"] == 1
    assert runs[str(run_id)]["viewed_revision"] is None
    assert runs[str(skipped_id)]["revision"] == 0
    unviewed = _list_runs(admin_user, task_id, unviewed=True).json()["items"]
    assert [run["id"] for run in unviewed] == [str(run_id)]

    assert _view_run(admin_user, task_id, run_id, 2).status_code == 409
    assert _view_run(basic_user, task_id, run_id, 1).status_code == 404

    viewed = _view_run(admin_user, task_id, run_id, 1)
    viewed.raise_for_status()
    assert viewed.json()["viewed_revision"] == 1
    assert _unviewed_run_count(admin_user, task_id) == 0
    assert _list_runs(admin_user, task_id, unviewed=True).json()["items"] == []


def test_bulk_view_keeps_newer_run_results_unviewed(admin_user: DATestUser) -> None:
    response = _create_task(admin_user, status=ScheduledTaskStatus.PAUSED)
    response.raise_for_status()
    task_id = UUID(response.json()["id"])

    run_id = _insert_run_with_status(
        task_id,
        ScheduledTaskRunStatus.RUNNING,
        ScheduledTaskRunStatus.FAILED,
    )
    bulk = client.patch(
        _url(str(task_id), "runs", "viewed"),
        json={"revisions": {str(run_id): 1}},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    bulk.raise_for_status()
    assert [run["viewed_revision"] for run in bulk.json()["items"]] == [1]
    assert _unviewed_run_count(admin_user, task_id) == 0

    _set_run_status(run_id, ScheduledTaskRunStatus.RUNNING)
    _set_run_status(run_id, ScheduledTaskRunStatus.SUCCEEDED)
    assert _unviewed_run_count(admin_user, task_id) == 1

    stale = client.patch(
        _url(str(task_id), "runs", "viewed"),
        json={"revisions": {str(run_id): 1}},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    stale.raise_for_status()
    assert _unviewed_run_count(admin_user, task_id) == 1
