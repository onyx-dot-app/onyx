"""Tests for ``SnapshotManager`` — the in-process snapshot extractor used by
the local backend.

These tests do **not** require the Kubernetes backend. They exercise
``SnapshotManager.restore_snapshot`` directly with a stub file store so the
extraction-filter contract is pinned regardless of which deployment backend
the rest of the suite is configured for.

Originally lived in ``test_snapshot_restore.py`` (a K8s-only module) where it
was wasting ~30s of K8s pod time per run; moved here so it runs in the
non-K8s CI lane alongside the rest of the external-dependency unit suite.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pytest

from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.build.sandbox.manager.snapshot_manager import SnapshotManager


def test_restore_uses_data_filter_to_block_traversal(tmp_path: Path) -> None:
    """``SnapshotManager.restore_snapshot`` must use the ``data`` extraction
    filter so a forged archive containing a ``../`` member raises instead of
    silently escaping the target directory.

    This pins the contract on the shared local-backend extractor; the K8s
    backend takes a different code path (``tar -xzf`` in-pod) and is not
    covered here.
    """
    # Forge a tarball with a path-traversal entry.
    forged_path = tmp_path / "forged.tar.gz"
    with tarfile.open(forged_path, "w:gz") as tar:
        # A safe entry, so the archive isn't trivially empty.
        safe_info = tarfile.TarInfo(name="outputs/ok.txt")
        safe_bytes = b"safe\n"
        safe_info.size = len(safe_bytes)
        tar.addfile(safe_info, io.BytesIO(safe_bytes))

        # The malicious entry — escapes the extraction target via `..`.
        evil_info = tarfile.TarInfo(name="../../etc/pwned")
        evil_bytes = b"owned\n"
        evil_info.size = len(evil_bytes)
        tar.addfile(evil_info, io.BytesIO(evil_bytes))

    file_store = get_default_file_store()
    file_store.initialize()

    snap = SnapshotManager(file_store=file_store)
    target = tmp_path / "restore-target"
    target.mkdir()

    # Stage the forged archive directly on disk and feed it to the
    # extractor by patching the file store read. This isolates the
    # extraction-filter behaviour from the (file-store-backed) read path.
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as f:
        f.write(forged_path.read_bytes())
        local_archive = Path(f.name)

    class _StaticReader:
        def __init__(self, path: Path) -> None:
            self._fh = open(path, "rb")

        def read(self) -> bytes:
            return self._fh.read()

        def close(self) -> None:
            self._fh.close()

    def fake_read_file(file_id: str, **_kwargs: Any) -> Any:  # noqa: ARG001
        return _StaticReader(local_archive)

    snap._file_store = type(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "S",
        (),
        {"read_file": staticmethod(fake_read_file)},
    )()

    with pytest.raises((RuntimeError, tarfile.TarError)) as excinfo:
        snap.restore_snapshot(storage_path="ignored", target_path=target)

    # The "data" filter raises a clear ``LinkOutsideDestinationError`` or
    # similar; either way it must surface as an error, not silently allow
    # the traversal entry.
    assert "pwned" not in [p.name for p in target.rglob("*")], (
        "Traversal entry must not have been extracted"
    )
    # Sanity check: a generic IOError would be ambiguous; assert the
    # message references the filter or traversal.
    err_text = str(excinfo.value).lower()
    assert any(
        token in err_text
        for token in ("filter", "traversal", "outside", "unsafe", "tarfile")
    ), f"Error should reference safety filter rejection. Got: {excinfo.value}"
