"""Exercise the production scan against real session trees and hostile entries."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

import pytest

from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    OutputsManifestResponse,
)
from tests.common.paths import find_ancestor_containing

_DAEMON_DIR = (
    find_ancestor_containing("backend/onyx")
    / "backend/onyx/server/features/build/sandbox/image/sandbox_daemon"
)


@pytest.fixture()
def manifest_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(_DAEMON_DIR.parent))
    return importlib.import_module("sandbox_daemon.outputs_manifest")


@pytest.fixture()
def session(
    manifest_module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[UUID, Path]:
    session_id = uuid4()
    sessions_root = tmp_path / "sessions"
    outputs = sessions_root / str(session_id) / "outputs"
    outputs.mkdir(parents=True)
    monkeypatch.setattr(manifest_module, "SESSIONS_ROOT", sessions_root)
    return session_id, outputs


def test_module_cli_validates_requests_and_returns_json() -> None:
    command = [sys.executable, "-E", "-s", "-m", "sandbox_daemon.outputs_manifest"]
    result = subprocess.run(
        [*command, str(uuid4())],
        cwd=_DAEMON_DIR.parent,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    manifest = OutputsManifestResponse.model_validate_json(result.stdout)
    assert manifest.entries == []
    assert not manifest.complete
    invalid = subprocess.run(
        [*command, "../another-session"],
        cwd=_DAEMON_DIR.parent,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert invalid.returncode != 0
    assert not invalid.stdout


@pytest.mark.parametrize("workspace_exists", [False, True])
def test_missing_outputs_distinguishes_unrestored_workspace(
    manifest_module: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace_exists: bool,
) -> None:
    session_id = uuid4()
    sessions_root = tmp_path / "sessions"
    if workspace_exists:
        (sessions_root / str(session_id)).mkdir(parents=True)
    monkeypatch.setattr(manifest_module, "SESSIONS_ROOT", sessions_root)
    result = manifest_module.build_outputs_manifest(session_id)
    assert result.entries == []
    assert result.complete == workspace_exists


def test_inventory_visibility_metadata_and_no_content_reads(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, outputs = session
    for path in [
        "slides/deck.pptx",
        "slides/web/notes.md",
        "web/page.tsx",
        ".preview/slide.png",
        ".hidden.md",
        "slides/node_modules/pkg/README.md",
        "__pycache__/build.pyc",
        "nextjs.log",
    ]:
        target = outputs / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"first version")
    (outputs / "empty").mkdir()

    def fail_content_read(*_args: object) -> None:
        raise AssertionError("Inventory must not read file content")

    monkeypatch.setattr(os, "read", fail_content_read)
    result = manifest_module.build_outputs_manifest(session_id)
    assert result.complete
    assert [entry.path for entry in result.entries] == [
        "slides/deck.pptx",
        "slides/web/notes.md",
    ]
    deck = outputs / "slides/deck.pptx"
    first = result.entries[0]
    assert first.size == len(b"first version")
    assert first.mtime_ns == deck.stat().st_mtime_ns
    deck.write_bytes(b"other version")
    os.utime(deck, ns=(deck.stat().st_atime_ns, first.mtime_ns + 1_000_000))
    updated = manifest_module.build_outputs_manifest(session_id).entries[0]
    assert updated.size == first.size
    assert updated.mtime_ns != first.mtime_ns


def test_symlinks_and_special_files_never_followed(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
    tmp_path: Path,
) -> None:
    session_id, outputs = session
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"secret")
    (outputs / "escape").symlink_to(outside)
    (outputs / "file_link").symlink_to(outside / "secret.txt")
    os.mkfifo(outputs / "pipe")
    (outputs / "real.txt").write_bytes(b"ok")
    result = manifest_module.build_outputs_manifest(session_id)
    assert [entry.path for entry in result.entries] == ["real.txt"]
    assert result.complete


def test_same_size_overwrite_with_preserved_mtime_changes_metadata(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
) -> None:
    session_id, outputs = session
    report = outputs / "report.txt"
    report.write_text("first")
    original = report.stat()
    before = manifest_module.build_outputs_manifest(session_id).entries[0]

    report.write_text("other")
    os.utime(report, ns=(original.st_atime_ns, original.st_mtime_ns))
    after = manifest_module.build_outputs_manifest(session_id).entries[0]

    assert after.size == before.size
    assert after.mtime_ns == before.mtime_ns
    assert after.ctime_ns != before.ctime_ns
    assert after.ctime_ns == report.stat().st_ctime_ns


@pytest.mark.parametrize("component", ["sessions", "session", "outputs"])
def test_workspace_path_components_cannot_redirect_scan(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
    tmp_path: Path,
    component: str,
) -> None:
    session_id, outputs = session
    target = {
        "sessions": outputs.parent.parent,
        "session": outputs.parent,
        "outputs": outputs,
    }[component]
    moved = tmp_path / "redirected"
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=True)
    result = manifest_module.build_outputs_manifest(session_id)
    assert result.entries == []
    assert result.complete == (component == "outputs")


def test_unreadable_directory_marks_scan_incomplete(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
) -> None:
    if os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")
    session_id, outputs = session
    locked = outputs / "locked"
    locked.mkdir()
    (locked / "hidden.txt").write_bytes(b"x")
    locked.chmod(0o000)
    try:
        result = manifest_module.build_outputs_manifest(session_id)
    finally:
        locked.chmod(0o755)
    assert result.entries == []
    assert not result.complete


def test_entry_budget_counts_ignored_entries_across_directories(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, outputs = session
    for directory in ["a", "b", "c"]:
        (outputs / directory).mkdir()
        for index in range(4):
            (outputs / directory / f".ignored-{index}").write_text("hidden")
    monkeypatch.setattr(manifest_module, "MANIFEST_MAX_ENTRIES", 7)
    scanned = 0
    real_scandir = os.scandir

    @contextmanager
    def count_scandir(fd: int) -> Iterator[Iterator[os.DirEntry[str]]]:
        def entries(source: Iterator[os.DirEntry[str]]) -> Iterator[os.DirEntry[str]]:
            nonlocal scanned
            for entry in source:
                scanned += 1
                yield entry

        with real_scandir(fd) as source:
            yield entries(source)

    monkeypatch.setattr(os, "scandir", count_scandir)
    result = manifest_module.build_outputs_manifest(session_id)
    assert scanned == 7
    assert result.entries == []
    assert not result.complete


def test_depth_limit_marks_scan_incomplete(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, outputs = session
    (outputs / "a/b").mkdir(parents=True)
    (outputs / "a/b/deep.txt").write_text("deep")
    (outputs / "a/visible.txt").write_text("visible")
    monkeypatch.setattr(manifest_module, "MANIFEST_MAX_DEPTH", 1)
    result = manifest_module.build_outputs_manifest(session_id)
    assert [entry.path for entry in result.entries] == ["a/visible.txt"]
    assert not result.complete


def test_directory_swapped_for_symlink_during_scan_is_not_followed(
    manifest_module: ModuleType,
    session: tuple[UUID, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id, outputs = session
    (outputs / "child").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    real_open = os.open

    def swap_before_open(
        path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if path == "child":
            (outputs / "child").rmdir()
            (outputs / "child").symlink_to(outside, target_is_directory=True)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_open)
    result = manifest_module.build_outputs_manifest(session_id)
    assert result.entries == []
    assert not result.complete
