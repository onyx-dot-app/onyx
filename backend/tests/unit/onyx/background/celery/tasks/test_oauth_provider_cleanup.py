from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from psycopg2.errors import UndefinedTable
from sqlalchemy.exc import ProgrammingError

from onyx.background.celery.tasks import beat_schedule
from onyx.background.celery.tasks.oauth_provider import tasks
from onyx.configs.constants import OnyxCeleryPriority, OnyxCeleryQueues, OnyxCeleryTask
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def test_cleanup_schedule_routes_to_primary_in_both_modes() -> None:
    tenant = next(
        item
        for item in beat_schedule.beat_task_templates
        if item["task"] == OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_RECORDS
    )
    assert tenant["schedule"] == timedelta(hours=1)
    assert tenant["options"] == {
        "queue": OnyxCeleryQueues.PRIMARY,
        "priority": OnyxCeleryPriority.LOW,
        "expires": beat_schedule.BEAT_EXPIRES_DEFAULT,
        "skip_gated": False,
        "work_gated": True,
    }
    cloud = beat_schedule.generate_cloud_tasks(
        beat_schedule.beat_cloud_tasks,
        [tenant],
        beat_schedule.CLOUD_BEAT_MULTIPLIER_DEFAULT,
    )
    generated = next(
        item
        for item in cloud
        if item.get("kwargs", {}).get("task_name") == tenant["task"]
    )
    assert generated["schedule"] == timedelta(hours=8)
    assert generated["kwargs"]["queue"] == OnyxCeleryQueues.PRIMARY
    assert generated["kwargs"]["priority"] == OnyxCeleryPriority.LOW
    assert generated["kwargs"]["expires"] == beat_schedule.BEAT_EXPIRES_DEFAULT
    assert generated["kwargs"]["skip_gated"] is False
    assert generated["kwargs"]["work_gated"] is True
    catalog = next(
        item
        for item in cloud
        if item["task"] == OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_CLIENTS
    )
    assert catalog["name"].startswith("cloud_")
    assert catalog["schedule"] == timedelta(hours=1)
    assert catalog["options"]["queue"] == OnyxCeleryQueues.PRIMARY
    assert catalog["options"]["priority"] == OnyxCeleryPriority.LOW
    assert catalog["options"]["expires"] == beat_schedule.BEAT_EXPIRES_DEFAULT
    if not MULTI_TENANT:
        scheduled = {item["task"]: item for item in beat_schedule.tasks_to_schedule}
        assert OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_RECORDS in scheduled
        assert OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_CLIENTS in scheduled
        options = scheduled[OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_RECORDS]["options"]
        assert "skip_gated" not in options
        assert "work_gated" not in options


def test_registered_tasks_use_separate_factories_and_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.background.celery.apps.primary import celery_app

    celery_app.loader.import_default_modules()
    tenant_factory, catalog_factory = MagicMock(), MagicMock()
    seen_tenants: list[str | None] = []

    def observe_tenant(*_args: object, **_kwargs: object) -> int:
        seen_tenants.append(CURRENT_TENANT_ID_CONTEXTVAR.get())
        return 0

    monkeypatch.setattr(tasks, "get_session_with_current_tenant", tenant_factory)
    monkeypatch.setattr(tasks, "get_catalog_session", catalog_factory)
    monkeypatch.setattr(
        tasks, "cleanup_oauth_provider_tokens__no_commit", observe_tenant
    )
    monkeypatch.setattr(
        tasks, "cleanup_oauth_provider_grants__no_commit", Mock(return_value=0)
    )
    monkeypatch.setattr(
        tasks, "cleanup_oauth_provider_clients__no_commit", observe_tenant
    )
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(None)
    try:
        assert (
            celery_app.tasks[OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_RECORDS](
                tenant_id="tenant_cleanup"
            )
            == 0
        )
        tenant_factory.assert_called_once()
        catalog_factory.assert_not_called()
        assert seen_tenants == ["tenant_cleanup"]
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() is None
        assert celery_app.tasks[OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_CLIENTS]() == 0
        catalog_factory.assert_called_once()
        assert seen_tenants == ["tenant_cleanup", POSTGRES_DEFAULT_SCHEMA]
        assert CURRENT_TENANT_ID_CONTEXTVAR.get() is None
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def test_primary_worker_registers_cleanup_tasks() -> None:
    from onyx.background.celery.apps.primary import celery_app

    celery_app.loader.import_default_modules()
    assert OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_RECORDS in celery_app.tasks
    assert OnyxCeleryTask.CLEANUP_OAUTH_PROVIDER_CLIENTS in celery_app.tasks


def test_cleanup_budget_stops_even_with_a_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value
    delete = Mock(return_value=1000)
    monkeypatch.setattr(tasks, "get_catalog_session", factory)
    monkeypatch.setattr(tasks, "cleanup_oauth_provider_clients__no_commit", delete)
    monkeypatch.setattr(
        tasks, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 61]))
    )
    assert tasks._run_cleanup(catalog=True) == 1000
    delete.assert_called_once()
    session.commit.assert_called_once()


def test_tenant_cleanup_runs_both_helpers_until_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = MagicMock()
    operations = Mock()
    operations.tokens.side_effect = [1000, 0, 0]
    operations.grants.side_effect = [0, 3, 0]
    monkeypatch.setattr(tasks, "get_session_with_current_tenant", factory)
    monkeypatch.setattr(
        tasks, "cleanup_oauth_provider_tokens__no_commit", operations.tokens
    )
    monkeypatch.setattr(
        tasks, "cleanup_oauth_provider_grants__no_commit", operations.grants
    )
    assert tasks._run_cleanup(catalog=False) == 1003
    assert [call[0] for call in operations.mock_calls] == ["tokens", "grants"] * 3
    assert factory.return_value.__enter__.return_value.commit.call_count == 3


def test_cleanup_stops_at_batch_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = MagicMock()
    monkeypatch.setattr(tasks, "get_catalog_session", factory)
    monkeypatch.setattr(
        tasks, "cleanup_oauth_provider_clients__no_commit", Mock(return_value=1000)
    )
    monkeypatch.setattr(tasks, "time", SimpleNamespace(monotonic=lambda: 0))
    assert tasks._run_cleanup(catalog=True) == 1000 * tasks._MAX_BATCHES
    assert (
        factory.return_value.__enter__.return_value.commit.call_count
        == tasks._MAX_BATCHES
    )


@pytest.mark.parametrize("missing_table", [True, False])
def test_cleanup_skips_only_missing_tables(
    monkeypatch: pytest.MonkeyPatch, missing_table: bool
) -> None:
    factory = MagicMock()
    original = (
        UndefinedTable("not migrated") if missing_table else ValueError("bad SQL")
    )
    error = ProgrammingError("cleanup", {}, original)
    monkeypatch.setattr(tasks, "get_catalog_session", factory)
    monkeypatch.setattr(
        tasks, "cleanup_oauth_provider_clients__no_commit", Mock(side_effect=error)
    )
    if missing_table:
        assert tasks._run_cleanup(catalog=True) == 0
    else:
        with pytest.raises(ProgrammingError):
            tasks._run_cleanup(catalog=True)
    factory.return_value.__enter__.return_value.commit.assert_not_called()


def test_catalog_task_accepts_both_scheduler_signatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup = Mock(return_value=0)
    monkeypatch.setattr(tasks, "_run_cleanup", cleanup)
    assert tasks.cleanup_oauth_provider_clients.run() == 0
    assert tasks.cleanup_oauth_provider_clients.run(tenant_id="public") == 0
    assert cleanup.call_count == 2
    cleanup.assert_called_with(catalog=True)


def test_missing_table_after_committed_batch_preserves_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = MagicMock()
    monkeypatch.setattr(tasks, "get_catalog_session", factory)
    monkeypatch.setattr(
        tasks,
        "cleanup_oauth_provider_clients__no_commit",
        Mock(
            side_effect=[2, ProgrammingError("cleanup", {}, UndefinedTable("missing"))]
        ),
    )
    assert tasks._run_cleanup(catalog=True) == 2
    factory.return_value.__enter__.return_value.commit.assert_called_once()
