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
from onyx.server.features.build.sandbox.manager.snapshot_manager import SnapshotManager


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


@pytest.fixture
def store() -> _FakeFileStore:
    return _FakeFileStore()


@pytest.fixture
def manager(store: _FakeFileStore) -> SnapshotManager:
    return SnapshotManager(cast(FileStore, store))


def test_create_snapshot_from_stream_persists_with_expected_metadata(
    store: _FakeFileStore, manager: SnapshotManager
) -> None:
    """Storage path / display name / origin / metadata must remain stable."""
    payload = b"a" * 1024
    snapshot_id, storage_path, size = manager.create_snapshot_from_stream(
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


def test_create_snapshot_from_stream_uses_size_hint(
    manager: SnapshotManager,
) -> None:
    """With a size hint, the manager skips spooling to disk and trusts the caller."""
    payload = b"hint-data"
    _id, _path, size = manager.create_snapshot_from_stream(
        stream=io.BytesIO(payload),
        sandbox_id="s",
        tenant_id="t",
        size_hint=999,
    )
    assert size == 999


def test_restore_snapshot_to_stream_writes_stored_bytes(
    manager: SnapshotManager,
) -> None:
    """Bytes saved via ``save_file`` should round-trip through the streaming reader."""
    payload = b"snapshot-bytes-to-restore"
    _id, storage_path, _size = manager.create_snapshot_from_stream(
        stream=io.BytesIO(payload),
        sandbox_id="s",
        tenant_id="t",
    )
    sink = io.BytesIO()
    manager.restore_snapshot_to_stream(storage_path, sink)
    assert sink.getvalue() == payload
