"""Unit tests for the streaming helpers on ``SnapshotManager``.

Production callers (Docker backend) pipe tar bytes through these helpers
without ever materializing a snapshot on the api_server filesystem. The
helpers are content-agnostic but the path/display-name/metadata contract
must stay stable, so we assert it here against a fake ``FileStore``.
"""

from __future__ import annotations

import io
from typing import Any
from typing import cast
from typing import IO

import pytest

from onyx.configs.constants import FileOrigin
from onyx.file_store.file_store import FileStore
from onyx.server.features.build.sandbox.snapshot_manager import SnapshotManager


class _FakeFileStore:
    """Minimal in-memory FileStore double."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self._content: dict[str, bytes] = {}

    def save_file(
        self,
        *,
        content: IO[bytes],
        display_name: str,
        file_origin: FileOrigin,
        file_type: str,
        file_id: str,
        file_metadata: dict[str, Any],
    ) -> None:
        data = content.read()
        self._content[file_id] = data
        self.saved.append(
            {
                "display_name": display_name,
                "file_origin": file_origin,
                "file_type": file_type,
                "file_id": file_id,
                "file_metadata": file_metadata,
                "size": len(data),
            }
        )

    def read_file(self, file_id: str, use_tempfile: bool = False) -> IO[bytes]:  # noqa: ARG002
        return io.BytesIO(self._content[file_id])

    def delete_file(self, file_id: str, error_on_missing: bool = True) -> None:
        if file_id not in self._content and error_on_missing:
            raise FileNotFoundError(file_id)
        self._content.pop(file_id, None)

    def has_file(
        self,
        file_id: str,
        file_origin: FileOrigin,  # noqa: ARG002
        file_type: str,  # noqa: ARG002
    ) -> bool:
        return file_id in self._content


@pytest.fixture
def store() -> _FakeFileStore:
    return _FakeFileStore()


@pytest.fixture
def manager(store: _FakeFileStore) -> SnapshotManager:
    return SnapshotManager(cast(FileStore, store))


def test_persist_snapshot_from_stream_persists_with_expected_metadata(
    store: _FakeFileStore, manager: SnapshotManager
) -> None:
    """Storage path / display name / origin / metadata must remain stable."""
    payload = b"a" * 1024
    snapshot_id, storage_path, size = manager.persist_snapshot_from_stream(
        stream=io.BytesIO(payload),
        sandbox_id="sandbox-xyz",
        tenant_id="tenant-abc",
    )
    assert size == len(payload)
    assert (
        storage_path == f"sandbox-snapshots/tenant-abc/sandbox-xyz/{snapshot_id}.tar.gz"
    )

    assert len(store.saved) == 1
    saved = store.saved[0]
    assert saved["file_origin"] == FileOrigin.SANDBOX_SNAPSHOT
    assert saved["file_type"] == "application/gzip"
    assert saved["file_id"] == storage_path
    assert saved["display_name"] == (
        f"sandbox-snapshot-sandbox-xyz-{snapshot_id}.tar.gz"
    )
    assert saved["file_metadata"] == {
        "sandbox_id": "sandbox-xyz",
        "tenant_id": "tenant-abc",
        "snapshot_id": snapshot_id,
    }
    assert saved["size"] == len(payload)


def test_restore_snapshot_to_stream_writes_stored_bytes(
    manager: SnapshotManager,
) -> None:
    """Bytes saved via ``save_file`` should round-trip through the streaming reader."""
    payload = b"snapshot-bytes-to-restore"
    _id, storage_path, _size = manager.persist_snapshot_from_stream(
        stream=io.BytesIO(payload),
        sandbox_id="s",
        tenant_id="t",
    )
    sink = io.BytesIO()
    manager.restore_snapshot_to_stream(storage_path, sink)
    assert sink.getvalue() == payload


def test_opencode_history_snapshot_uses_stable_sandbox_level_path(
    store: _FakeFileStore,
    manager: SnapshotManager,
) -> None:
    payload = b"opencode-history"

    storage_path, size = manager.persist_opencode_snapshot_from_stream(
        stream=io.BytesIO(payload),
        sandbox_id="sandbox-xyz",
        tenant_id="tenant-abc",
    )

    assert size == len(payload)
    assert (
        storage_path
        == "sandbox-snapshots/tenant-abc/sandbox-xyz/opencode-history.tar.gz"
    )
    assert manager.has_opencode_history_snapshot("tenant-abc", "sandbox-xyz") is True

    saved = store.saved[-1]
    assert saved["file_origin"] == FileOrigin.SANDBOX_SNAPSHOT
    assert saved["file_type"] == "application/gzip"
    assert saved["file_id"] == storage_path
    assert saved["display_name"] == "sandbox-opencode-history-sandbox-xyz.tar.gz"
    assert saved["file_metadata"] == {
        "sandbox_id": "sandbox-xyz",
        "tenant_id": "tenant-abc",
        "snapshot_kind": "opencode_history",
    }

    sink = io.BytesIO()
    manager.restore_snapshot_to_stream(storage_path, sink)
    assert sink.getvalue() == payload


def test_opencode_history_snapshot_overwrites_latest_for_sandbox(
    manager: SnapshotManager,
) -> None:
    manager.persist_opencode_snapshot_from_stream(
        stream=io.BytesIO(b"old"),
        sandbox_id="sandbox-xyz",
        tenant_id="tenant-abc",
    )
    manager.persist_opencode_snapshot_from_stream(
        stream=io.BytesIO(b"new"),
        sandbox_id="sandbox-xyz",
        tenant_id="tenant-abc",
    )

    sink = io.BytesIO()
    manager.restore_snapshot_to_stream(
        SnapshotManager.opencode_history_storage_path("tenant-abc", "sandbox-xyz"),
        sink,
    )
    assert sink.getvalue() == b"new"


def test_opencode_history_snapshot_rejects_empty_stream(
    manager: SnapshotManager,
) -> None:
    with pytest.raises(RuntimeError, match="empty"):
        manager.persist_opencode_snapshot_from_stream(
            stream=io.BytesIO(b""),
            sandbox_id="sandbox-xyz",
            tenant_id="tenant-abc",
        )


def test_delete_opencode_history_snapshot_removes_stable_path(
    manager: SnapshotManager,
) -> None:
    manager.persist_opencode_snapshot_from_stream(
        stream=io.BytesIO(b"history"),
        sandbox_id="sandbox-xyz",
        tenant_id="tenant-abc",
    )

    manager.delete_opencode_history_snapshot("tenant-abc", "sandbox-xyz")

    assert manager.has_opencode_history_snapshot("tenant-abc", "sandbox-xyz") is False
