"""Tests for the _build_targz function in kubernetes_sandbox_manager.py."""

import hashlib
import io
import os
import tarfile
import tempfile

import pytest

from onyx.server.features.build.sandbox.image.sandbox_daemon.models import (
    PUSH_MAX_ARCHIVE_BYTES,
    PUSH_MAX_CONTENT_BYTES,
    PUSH_MAX_FILES,
    PUSH_MAX_PATH_BYTES,
    PUSH_VERSION_NAME_BYTES,
    push_path_byte_limit,
    push_version_directory,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    _build_targz,
)
from onyx.server.features.build.sandbox.models import FatalWriteError, FileSet

_MANAGER_MODULE = (
    "onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager"
)


def _build(files: FileSet) -> tuple[bytes, str]:
    archive_file = io.BytesIO()
    sha = _build_targz(files, archive_file, mount_path="/workspace/managed/skills")
    return archive_file.getvalue(), sha


def test_round_trip() -> None:
    files: FileSet = {
        "hello.txt": b"hello world",
        "sub/dir/deep.py": b"print('deep')",
        "empty": b"",
    }
    raw, sha = _build(files)

    # Extract and verify
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        members = tar.getmembers()
        extracted: dict[str, bytes] = {}
        for m in members:
            f = tar.extractfile(m)
            if f is not None:
                extracted[m.name] = f.read()

    for name, data in files.items():
        assert name in extracted, f"Missing entry: {name}"
        assert extracted[name] == data, f"Content mismatch for {name}"


def test_deterministic() -> None:
    files: FileSet = {
        "b.txt": b"bbb",
        "a.txt": b"aaa",
        "c.txt": b"ccc",
    }
    raw1, sha1 = _build(files)
    raw2, sha2 = _build(files)

    assert raw1[4:8] == b"\0\0\0\0"
    assert raw1 == raw2
    assert sha1 == sha2


def test_sorted_entries() -> None:
    files: FileSet = {
        "zebra.txt": b"z",
        "alpha.txt": b"a",
        "middle.txt": b"m",
    }
    raw, _ = _build(files)

    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        names = [m.name for m in tar.getmembers()]

    assert names == sorted(names)


def test_empty_dict() -> None:
    raw, sha = _build({})

    # Should be a valid tar.gz with no entries
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        assert tar.getmembers() == []

    # SHA should still be valid
    assert sha == hashlib.sha256(raw).hexdigest()


def test_oversized_bundle_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{_MANAGER_MODULE}.PUSH_MAX_CONTENT_BYTES", 100)
    files: FileSet = {"big.bin": b"x" * 200}
    with pytest.raises(FatalWriteError, match="exceeds"):
        _build(files)


def test_too_many_files_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{_MANAGER_MODULE}.PUSH_MAX_FILES", 2)
    files: FileSet = {"a": b"", "b": b"", "c": b""}
    with pytest.raises(FatalWriteError, match="more than 2"):
        _build(files)


def test_archive_over_wire_limit_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(f"{_MANAGER_MODULE}.PUSH_MAX_ARCHIVE_BYTES", 10)
    with pytest.raises(FatalWriteError, match="Archive size"):
        _build({"a.txt": b"a"})


def test_full_content_limit_fits_wire_limit() -> None:
    """Incompressible files at the content and file limits fit the wire limit.

    Uses the archive layout the sender writes, with the longest allowed path,
    so tar headers, PAX records and deflate overhead are all at their worst.
    """
    file_count = PUSH_MAX_FILES
    file_size = PUSH_MAX_CONTENT_BYTES // file_count
    # Odd sizes force the most tar padding per entry.
    if file_size % 2 == 0:
        file_size -= 1
    data = os.urandom(file_size)
    path_limit = push_path_byte_limit(
        str(
            push_version_directory(
                "/workspace/managed/skills", "0" * PUSH_VERSION_NAME_BYTES
            )
        )
    )
    prefix = "d/" * ((path_limit - 16) // 2)
    files: FileSet = {
        f"{prefix}{i:08d}.bin"[-PUSH_MAX_PATH_BYTES:]: data for i in range(file_count)
    }
    assert all(len(name.encode()) <= PUSH_MAX_PATH_BYTES for name in files)
    assert len(files) == file_count

    with tempfile.TemporaryFile() as archive_file:
        _build_targz(files, archive_file, mount_path="/workspace/managed/skills")
        archive_size = archive_file.seek(0, os.SEEK_END)

    assert archive_size <= PUSH_MAX_ARCHIVE_BYTES


def test_too_many_implied_folders_rejected_before_archive_write() -> None:
    files = {f"skill-{i}/a/b/c/SKILL.md": b"x" for i in range(2600)}
    archive_file = io.BytesIO()
    with pytest.raises(FatalWriteError, match="10000 folders"):
        _build_targz(files, archive_file, mount_path="/workspace/managed/skills")
    assert archive_file.tell() == 0


def test_utf8_path_limit_rejected_before_archive_write() -> None:
    path = "é" * (PUSH_MAX_PATH_BYTES // 2) + "x"
    archive_file = io.BytesIO()
    with pytest.raises(FatalWriteError, match="Path name longer"):
        _build_targz({path: b"x"}, archive_file, mount_path="/workspace/managed/skills")
    assert archive_file.tell() == 0


@pytest.mark.parametrize(
    "path",
    ["big/" + "a" * 256, "big/" + "é" * 128, "/".join(["a" * 200] * 20 + ["b" * 76])],
)
def test_filesystem_path_limits_rejected_before_archive_write(path: str) -> None:
    archive_file = io.BytesIO()
    with pytest.raises(FatalWriteError, match="Path"):
        _build_targz({path: b"x"}, archive_file, mount_path="/workspace/managed/skills")
    assert archive_file.tell() == 0
