"""Tests for _validate_opencode_history_archive in docker_sandbox_manager."""

from __future__ import annotations

import gzip
import io
import tarfile
from collections.abc import Sequence
from pathlib import Path

import pytest

from onyx.server.features.build.sandbox.docker.docker_sandbox_manager import (
    _validate_opencode_history_archive,
)

ARCHIVE_ROOT = ".opencode-data"


def _archive(members: Sequence[tarfile.TarInfo]) -> bytes:
    """Pack members into a gzip tar, giving regular files a payload."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for member in members:
            if member.isreg():
                tar.addfile(member, io.BytesIO(b"x" * member.size))
            else:
                tar.addfile(member)
    return buf.getvalue()


def _file(name: str, size: int = 4) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name=name)
    member.size = size
    member.mode = 0o644
    return member


def _directory(name: str) -> tarfile.TarInfo:
    member = tarfile.TarInfo(name=name)
    member.type = tarfile.DIRTYPE
    member.mode = 0o755
    return member


def _special(name: str, member_type: bytes, linkname: str = "") -> tarfile.TarInfo:
    member = tarfile.TarInfo(name=name)
    member.type = member_type
    member.linkname = linkname
    return member


def test_valid_tree_accepted() -> None:
    archive = _archive(
        [
            _directory(ARCHIVE_ROOT),
            _directory(f"{ARCHIVE_ROOT}/opencode"),
            _file(f"{ARCHIVE_ROOT}/opencode/opencode.db", size=16),
            _file(f"{ARCHIVE_ROOT}/opencode/project/session/message.json"),
            _file(f"./{ARCHIVE_ROOT}/auth.json"),
        ]
    )

    _validate_opencode_history_archive(archive)


def test_archive_built_like_the_sidecar_accepted(tmp_path: Path) -> None:
    """Mirrors create_opencode_history_archive_file's tar.add(arcname=...) shape."""
    staged_root = tmp_path / ARCHIVE_ROOT
    (staged_root / "opencode").mkdir(parents=True)
    (staged_root / "opencode" / "opencode.db").write_bytes(b"SQLite format 3\x00")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(staged_root, arcname=ARCHIVE_ROOT, recursive=True)

    _validate_opencode_history_archive(buf.getvalue())


def test_empty_archive_accepted() -> None:
    _validate_opencode_history_archive(_archive([]))


@pytest.mark.parametrize(
    "name",
    [
        "/etc/passwd",
        f"/{ARCHIVE_ROOT}/opencode.db",
        f"{ARCHIVE_ROOT}/../evil",
        "../evil",
        f"{ARCHIVE_ROOT}/opencode/../../evil",
        "evil.sh",
        "managed/.onyx/firewall-init.sh",
        ".opencode-database/evil",
        f"{ARCHIVE_ROOT}-evil/payload",
    ],
)
def test_member_outside_archive_root_rejected(name: str) -> None:
    with pytest.raises(RuntimeError, match="escapes"):
        _validate_opencode_history_archive(_archive([_file(name)]))


@pytest.mark.parametrize(
    ("member_type", "linkname"),
    [
        (tarfile.SYMTYPE, "/etc/passwd"),
        (tarfile.LNKTYPE, f"{ARCHIVE_ROOT}/opencode/opencode.db"),
        (tarfile.CHRTYPE, ""),
        (tarfile.BLKTYPE, ""),
        (tarfile.FIFOTYPE, ""),
    ],
)
def test_special_member_rejected(member_type: bytes, linkname: str) -> None:
    """Names stay inside the root so only the member type can fail the check."""
    archive = _archive(
        [_special(f"{ARCHIVE_ROOT}/opencode/entry", member_type, linkname)]
    )

    with pytest.raises(RuntimeError, match="not a file or directory"):
        _validate_opencode_history_archive(archive)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not a gzip archive",
        gzip.compress(b"gzip, but not a tar"),
        _archive([_file(f"{ARCHIVE_ROOT}/opencode.db", size=8192)])[:60],
    ],
    ids=["empty", "not-gzip", "gzip-not-tar", "truncated-gzip"],
)
def test_unreadable_archive_rejected(payload: bytes) -> None:
    with pytest.raises(RuntimeError, match="unreadable"):
        _validate_opencode_history_archive(payload)
