import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import (
    SandboxResource,
    SandboxResourceKind,
)
from onyx.server.features.build.session import resource_cleanup as cleanup


@pytest.fixture
def collector(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    manager = MagicMock(spec=SandboxManager)
    cache = MagicMock()
    cache.get.return_value = None
    monkeypatch.setattr(cleanup, "get_cache_backend", lambda **_kwargs: cache)
    monkeypatch.setattr(cleanup, "get_session_with_current_tenant", MagicMock())
    monkeypatch.setattr(cleanup, "get_stale_provisioning_sandboxes", lambda *_args: [])
    return manager, cache


def _resource(**updates: object) -> SandboxResource:
    values: dict[str, object] = {
        "sandbox_id": uuid4(),
        "tenant_id": "tenant-a",
        "kind": SandboxResourceKind.POD,
        "name": "sandbox-12345678",
        "instance_id": "old-uid",
        "provisioning_attempt_number": 1,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    values.update(updates)
    return SandboxResource.model_validate(values)


@pytest.mark.parametrize(
    "status",
    [None, SandboxStatus.SLEEPING, SandboxStatus.TERMINATED],
)
def test_collects_orphans_and_failed_or_inactive_runtime_resources(
    status: SandboxStatus | None,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource()
    manager.iter_resources.return_value = iter([resource])
    row = (
        None
        if status is None
        else Sandbox(
            id=resource.sandbox_id,
            user_id=uuid4(),
            status=status,
            provisioning_attempt_number=1,
        )
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert manager.delete_resource.call_args.args[0] == resource


@pytest.mark.parametrize(
    "status", [SandboxStatus.RUNNING, SandboxStatus.PROVISIONING, SandboxStatus.FAILED]
)
def test_preserves_live_or_provisioning_owners(
    status: SandboxStatus,
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource()
    manager.iter_resources.return_value = iter([resource])
    row = Sandbox(
        id=resource.sandbox_id,
        user_id=uuid4(),
        status=status,
        provisioning_attempt_number=1,
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    manager.delete_resource.assert_not_called()


def test_db_read_failure_does_not_authorize_orphan_deletion(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    manager.iter_resources.return_value = iter([_resource()])
    monkeypatch.setattr(
        cleanup,
        "get_sandbox_by_id",
        MagicMock(side_effect=RuntimeError("DB unavailable")),
    )
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    manager.delete_resource.assert_not_called()


@pytest.mark.parametrize(
    "updates",
    [
        {"tenant_id": "tenant-b"},
        {"created_at": datetime.now(timezone.utc)},
        {"provisioning_attempt_number": 2},
    ],
)
def test_preserves_foreign_fresh_or_newer_generation_resources(
    updates: dict[str, object],
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    resource = _resource(**updates)
    manager.iter_resources.return_value = iter([resource])
    row = Sandbox(
        id=resource.sandbox_id,
        user_id=uuid4(),
        status=SandboxStatus.FAILED,
        provisioning_attempt_number=1,
    )
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: row)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    manager.delete_resource.assert_not_called()


def test_deletion_failure_does_not_skip_other_resources(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, cache = collector
    resources = [_resource(kind=SandboxResourceKind.SERVICE), _resource()]
    manager.iter_resources.return_value = iter(resources)
    manager.delete_resource.side_effect = [
        RuntimeError("Service deletion failed"),
        None,
    ]
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert manager.delete_resource.call_count == 2
    cache.set.assert_called_once()


def test_expires_stale_provisioning_without_any_runtime_resources(
    collector: tuple[MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    manager.iter_resources.return_value = iter(())
    row = Sandbox(id=uuid4(), user_id=uuid4(), provisioning_attempt_number=3)
    monkeypatch.setattr(
        cleanup, "get_stale_provisioning_sandboxes", lambda *_args: [row]
    )
    expire = MagicMock()
    monkeypatch.setattr(cleanup, "fail_stale_provisioning__no_commit", expire)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    assert expire.call_args.args[1:3] == (row.id, 3)


def test_lost_claim_stops_deletion(
    collector: tuple[MagicMock, MagicMock],
    runtime_lock_cache: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _cache = collector
    manager.iter_resources.return_value = iter([_resource()])
    runtime_lock_cache.lock.return_value.owned.return_value = False
    monkeypatch.setattr(cleanup, "get_sandbox_by_id", lambda *_args: None)
    cleanup.reconcile_sandbox_resources(
        manager, "tenant-a", time.monotonic() + 60, lambda: None
    )
    manager.delete_resource.assert_not_called()
