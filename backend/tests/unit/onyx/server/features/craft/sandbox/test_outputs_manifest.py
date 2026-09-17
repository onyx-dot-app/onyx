"""Unit tests for the sandbox daemon's outputs manifest walk.

The manifest is the server's only view of the outputs tree, so the walk's
lstat discipline (symlinks never followed, non-regular files never described)
and its hash/size accuracy are load-bearing. The daemon modules are loaded
dynamically under the ``sandbox_daemon`` package name because their
in-container layout is not on the backend Python path.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from tests.common.paths import find_ancestor_containing

_DAEMON_DIR = (
    find_ancestor_containing("backend/onyx")
    / "backend"
    / "onyx"
    / "server"
    / "features"
    / "build"
    / "sandbox"
    / "image"
    / "sandbox_daemon"
)

# Same full module list as test_sandbox_daemon's loader, so whichever file
# runs first the other's cache guard sees every module and reuses it, and no
# model class gets two identities in one session.
_DAEMON_MODULES = (
    "contract",
    "extract",
    "snapshot",
    "opencode_history",
    "filesystem",
    "manifest",
    "server",
)


def _load_manifest_module() -> ModuleType:
    if "sandbox_daemon.manifest" in sys.modules:
        return sys.modules["sandbox_daemon.manifest"]

    sys.modules.setdefault("sandbox_daemon", types.ModuleType("sandbox_daemon"))
    for name in _DAEMON_MODULES:
        spec = importlib.util.spec_from_file_location(
            f"sandbox_daemon.{name}", str(_DAEMON_DIR / f"{name}.py")
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"sandbox_daemon.{name}"] = mod
        spec.loader.exec_module(mod)

    return sys.modules["sandbox_daemon.manifest"]


@pytest.fixture()
def manifest_module() -> ModuleType:
    return _load_manifest_module()


def test_missing_root_is_empty(manifest_module: ModuleType, tmp_path: Path) -> None:
    result = manifest_module.build_manifest_for_root(tmp_path / "outputs")
    assert result.entries == []
    assert not result.truncated


def test_files_and_directories_described(
    manifest_module: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "report.md").write_bytes(b"hello")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_bytes(b"<html>")

    result = manifest_module.build_manifest_for_root(tmp_path)
    by_path = {e.path: e for e in result.entries}

    assert set(by_path) == {"report.md", "web", "web/index.html"}
    assert by_path["web"].is_directory and by_path["web"].sha256 is None
    report = by_path["report.md"]
    assert report.size == 5
    assert report.sha256 is not None and report.mtime_ns is not None


def test_hash_tracks_content(manifest_module: ModuleType, tmp_path: Path) -> None:
    target = tmp_path / "deck.pptx"
    target.write_bytes(b"v1")
    first = {
        e.path: e for e in manifest_module.build_manifest_for_root(tmp_path).entries
    }["deck.pptx"].sha256
    target.write_bytes(b"v2")
    second = {
        e.path: e for e in manifest_module.build_manifest_for_root(tmp_path).entries
    }["deck.pptx"].sha256
    assert first != second


def test_symlinks_skipped_never_followed(
    manifest_module: ModuleType, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    root = tmp_path / "outputs"
    root.mkdir()
    (root / "escape").symlink_to(outside)
    (root / "file_link").symlink_to(outside / "secret.txt")
    (root / "real.txt").write_bytes(b"ok")

    result = manifest_module.build_manifest_for_root(root)
    assert [e.path for e in result.entries] == ["real.txt"]
    assert result.skipped_symlinks == 2


def test_special_files_skipped(manifest_module: ModuleType, tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")
    (tmp_path / "real.txt").write_bytes(b"ok")

    result = manifest_module.build_manifest_for_root(tmp_path)
    assert [e.path for e in result.entries] == ["real.txt"]
    assert result.skipped_special == 1


def test_unreadable_directory_counted_not_listed(
    manifest_module: ModuleType, tmp_path: Path
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "hidden.txt").write_bytes(b"x")
    locked.chmod(0o000)
    try:
        result = manifest_module.build_manifest_for_root(tmp_path)
    finally:
        locked.chmod(0o755)
    assert [e.path for e in result.entries] == []
    assert result.skipped_unreadable == 1


def test_truncation_flags_instead_of_growing(
    manifest_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_module, "MANIFEST_MAX_ENTRIES", 3)
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_bytes(b"x")

    result = manifest_module.build_manifest_for_root(tmp_path)
    assert len(result.entries) == 3
    assert result.truncated


def test_oversize_file_listed_without_hash(
    manifest_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest_module, "MANIFEST_MAX_HASH_BYTES", 4)
    (tmp_path / "big.bin").write_bytes(b"x" * 10)
    (tmp_path / "small.bin").write_bytes(b"x")

    result = manifest_module.build_manifest_for_root(tmp_path)
    by_path = {e.path: e for e in result.entries}
    assert by_path["big.bin"].sha256 is None
    assert by_path["big.bin"].size == 10
    assert by_path["small.bin"].sha256 is not None


def test_session_descent_reaches_outputs(
    manifest_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = uuid4()
    sessions_root = tmp_path / "workspace" / "sessions"
    outputs = sessions_root / str(session_id) / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "deck.pptx").write_bytes(b"deck")
    monkeypatch.setattr(manifest_module, "SESSIONS_ROOT", sessions_root)

    result = manifest_module.build_outputs_manifest(session_id)
    assert [e.path for e in result.entries] == ["deck.pptx"]

    # A session directory swapped for a symlink yields nothing.
    other = uuid4()
    elsewhere = tmp_path / "elsewhere" / "outputs"
    elsewhere.mkdir(parents=True)
    (elsewhere / "leak.txt").write_bytes(b"leak")
    (sessions_root / str(other)).symlink_to(tmp_path / "elsewhere")
    assert manifest_module.build_outputs_manifest(other).entries == []
