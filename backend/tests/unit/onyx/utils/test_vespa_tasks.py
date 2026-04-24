from contextlib import contextmanager
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

    def __init__(self, tenant_id: str, object_id: str) -> None:  # noqa: ARG002
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
        lambda db_session, document_set_id: document_set,  # noqa: ARG005
    )

    def _delete(document_set_row: Any, db_session: Any) -> None:  # noqa: ARG001
        calls["deleted"] = True

    monkeypatch.setattr(vespa_tasks, "delete_document_set", _delete)

    def _mark(document_set_id: Any, db_session: Any) -> None:  # noqa: ARG001
        calls["synced"] = True

    monkeypatch.setattr(vespa_tasks, "mark_document_set_as_synced", _mark)

    monkeypatch.setattr(
        vespa_tasks,
        "update_sync_record_status",
        lambda db_session, entity_id, sync_type, sync_status, num_docs_synced: None,  # noqa: ARG005
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
        r=SimpleNamespace(  # ty: ignore[invalid-argument-type]
            scard=lambda key: 0  # noqa: ARG005
        ),
        db_session=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
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
        r=SimpleNamespace(  # ty: ignore[invalid-argument-type]
            scard=lambda key: 0  # noqa: ARG005
        ),
        db_session=SimpleNamespace(),  # ty: ignore[invalid-argument-type]
    )

    assert calls["deleted"] is True
    assert calls["synced"] is False


def test_vespa_metadata_sync_releases_session_before_http_calls(
    monkeypatch: Any,
) -> None:
    """Session must be closed before Vespa HTTP writes to avoid pooler drops
    mid-session. A second short-lived session is opened for the terminal
    mark_document_as_synced write."""

    events: list[str] = []

    @contextmanager
    def _fake_session() -> Any:
        events.append("session_open")
        try:
            yield SimpleNamespace()
        finally:
            events.append("session_close")

    monkeypatch.setattr(vespa_tasks, "get_session_with_current_tenant", _fake_session)
    monkeypatch.setattr(
        vespa_tasks,
        "get_active_search_settings",
        lambda *_a, **_kw: SimpleNamespace(primary=object(), secondary=None),
    )
    monkeypatch.setattr(
        vespa_tasks,
        "get_all_document_indices",
        lambda *_a, **_kw: [object()],
    )

    fake_doc = SimpleNamespace(boost=0, hidden=False, chunk_count=3)
    monkeypatch.setattr(vespa_tasks, "get_document", lambda *_a, **_kw: fake_doc)
    monkeypatch.setattr(
        vespa_tasks, "fetch_document_sets_for_document", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(
        vespa_tasks, "get_access_for_document", lambda *_a, **_kw: SimpleNamespace()
    )

    class _FakeRetryDocumentIndex:
        def __init__(self, document_index: Any) -> None:
            pass

        def update_single(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            events.append("vespa_update_single")

    monkeypatch.setattr(vespa_tasks, "RetryDocumentIndex", _FakeRetryDocumentIndex)

    def _mark(*_a: Any, **_kw: Any) -> None:
        events.append("mark_document_as_synced")

    monkeypatch.setattr(vespa_tasks, "mark_document_as_synced", _mark)

    result = vespa_tasks.vespa_metadata_sync_task.__wrapped__(  # ty: ignore[unresolved-attribute]
        "doc-1", tenant_id="tenant-1"
    )

    assert result is True
    # First session is fully closed before any Vespa HTTP call
    first_close = events.index("session_close")
    first_http = events.index("vespa_update_single")
    assert first_close < first_http, events
    # A second session is opened for the terminal sync marker
    assert events.count("session_open") == 2
    assert events.count("session_close") == 2
    mark_idx = events.index("mark_document_as_synced")
    assert first_http < mark_idx, events


def test_vespa_metadata_sync_handles_doc_with_none_chunk_count(
    monkeypatch: Any,
) -> None:
    """A valid doc with `chunk_count = None` (a legitimate model state) must
    still be pushed to Vespa and marked synced — not silently skipped."""

    events: list[str] = []

    @contextmanager
    def _fake_session() -> Any:
        events.append("session_open")
        try:
            yield SimpleNamespace()
        finally:
            events.append("session_close")

    monkeypatch.setattr(vespa_tasks, "get_session_with_current_tenant", _fake_session)
    monkeypatch.setattr(
        vespa_tasks,
        "get_active_search_settings",
        lambda *_a, **_kw: SimpleNamespace(primary=object(), secondary=None),
    )
    monkeypatch.setattr(
        vespa_tasks, "get_all_document_indices", lambda *_a, **_kw: [object()]
    )

    fake_doc = SimpleNamespace(boost=0, hidden=False, chunk_count=None)
    monkeypatch.setattr(vespa_tasks, "get_document", lambda *_a, **_kw: fake_doc)
    monkeypatch.setattr(
        vespa_tasks, "fetch_document_sets_for_document", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(
        vespa_tasks, "get_access_for_document", lambda *_a, **_kw: SimpleNamespace()
    )

    received_chunk_counts: list[int | None] = []

    class _FakeRetryDocumentIndex:
        def __init__(self, document_index: Any) -> None:
            pass

        def update_single(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            received_chunk_counts.append(kwargs["chunk_count"])
            events.append("vespa_update_single")

    monkeypatch.setattr(vespa_tasks, "RetryDocumentIndex", _FakeRetryDocumentIndex)

    def _mark(*_a: Any, **_kw: Any) -> None:
        events.append("mark_document_as_synced")

    monkeypatch.setattr(vespa_tasks, "mark_document_as_synced", _mark)

    result = vespa_tasks.vespa_metadata_sync_task.__wrapped__(  # ty: ignore[unresolved-attribute]
        "doc-2", tenant_id="tenant-2"
    )

    assert result is True
    assert received_chunk_counts == [None]
    assert "vespa_update_single" in events
    assert "mark_document_as_synced" in events
