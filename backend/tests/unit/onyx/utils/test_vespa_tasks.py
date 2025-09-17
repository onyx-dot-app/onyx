from types import SimpleNamespace
from typing import Any

from onyx.background.celery.tasks.vespa import tasks as vespa_tasks


class _StubRedisDocumentSet:
    """Lightweight stand-in for RedisDocumentSet used by monitor tests."""

    reset_called = False

    @staticmethod
    def get_id_from_fence_key(key: str) -> str | None:
        parts = key.split("_")
        return parts[-1] if len(parts) == 3 else None

    def __init__(self, tenant_id: str, object_id: str) -> None:
        self.taskset_key = f"documentset_taskset_{object_id}"
        self._payload = 0

    @property
    def fenced(self) -> bool:
        return True

    @property
    def payload(self) -> int:
        return self._payload

    def reset(self) -> None:
        self.__class__.reset_called = True


def _setup_common_patches(monkeypatch: Any, document_set: Any) -> dict[str, bool]:
    calls: dict[str, bool] = {"deleted": False, "synced": False}

    monkeypatch.setattr(vespa_tasks, "RedisDocumentSet", _StubRedisDocumentSet)

    monkeypatch.setattr(
        vespa_tasks,
        "get_document_set_by_id",
        lambda db_session, document_set_id: document_set,
    )

    def _delete(document_set_row: Any, db_session: Any) -> None:
        calls["deleted"] = True

    monkeypatch.setattr(vespa_tasks, "delete_document_set", _delete)

    def _mark(document_set_id: Any, db_session: Any) -> None:
        calls["synced"] = True

    monkeypatch.setattr(vespa_tasks, "mark_document_set_as_synced", _mark)

    monkeypatch.setattr(
        vespa_tasks,
        "update_sync_record_status",
        lambda db_session, entity_id, sync_type, sync_status, num_docs_synced: None,
    )

    return calls


def test_monitor_preserves_federated_only_document_set(monkeypatch: Any) -> None:
    document_set = SimpleNamespace(
        connector_credential_pairs=[],
        federated_connectors=[object()],
    )

    calls = _setup_common_patches(monkeypatch, document_set)

    vespa_tasks.monitor_document_set_taskset(
        tenant_id="tenant",
        key_bytes=b"documentset_fence_1",
        r=SimpleNamespace(scard=lambda key: 0),  # type: ignore[arg-type]
        db_session=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert calls["synced"] is True
    assert calls["deleted"] is False


def test_monitor_deletes_document_set_with_no_connectors(monkeypatch: Any) -> None:
    document_set = SimpleNamespace(
        connector_credential_pairs=[],
        federated_connectors=[],
    )

    calls = _setup_common_patches(monkeypatch, document_set)

    vespa_tasks.monitor_document_set_taskset(
        tenant_id="tenant",
        key_bytes=b"documentset_fence_2",
        r=SimpleNamespace(scard=lambda key: 0),  # type: ignore[arg-type]
        db_session=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert calls["deleted"] is True
    assert calls["synced"] is False
