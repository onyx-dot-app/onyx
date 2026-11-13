import runpy
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from onyx.background.celery.tasks import beat_schedule
from onyx.background.celery.tasks.build import tasks
from onyx.configs.constants import OnyxCeleryTask
from onyx.server.features.build import configs
from shared_configs import configs as shared_configs


@pytest.mark.parametrize("multi_tenant", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_reconciler_schedule_requires_craft(
    monkeypatch: pytest.MonkeyPatch, multi_tenant: bool, enabled: bool
) -> None:
    monkeypatch.setattr(configs, "ENABLE_CRAFT", enabled)
    monkeypatch.setattr(shared_configs, "MULTI_TENANT", multi_tenant)
    schedule = runpy.run_path(beat_schedule.__file__)
    entries = schedule["beat_cloud_tasks"] + schedule["tasks_to_schedule"]
    reconciler_entries = [
        entry
        for entry in entries
        if entry["task"] == OnyxCeleryTask.RECONCILE_SANDBOX_RUNTIMES
    ]
    assert len(reconciler_entries) == int(enabled)
    if enabled:
        assert reconciler_entries[0]["schedule"] == timedelta(minutes=15)
        assert reconciler_entries[0]["options"]["expires"] == 15 * 60


@pytest.mark.parametrize("multi_tenant", [False, True])
def test_queued_reconciler_skips_backend_access_when_craft_is_disabled(
    monkeypatch: pytest.MonkeyPatch, multi_tenant: bool
) -> None:
    monkeypatch.setattr(tasks, "ENABLE_CRAFT", False)
    monkeypatch.setattr(tasks, "MULTI_TENANT", multi_tenant)
    manager = MagicMock(side_effect=AssertionError("Sandbox access is disabled"))
    tenants = MagicMock(side_effect=AssertionError("Tenant lookup is unnecessary"))
    monkeypatch.setattr(tasks, "get_sandbox_manager", manager)
    monkeypatch.setattr(tasks, "get_all_tenant_ids", tenants)

    tasks.reconcile_sandbox_runtimes_task.run()

    manager.assert_not_called()
    tenants.assert_not_called()
