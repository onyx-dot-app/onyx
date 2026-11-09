"""Tests for safe_extract_then_atomic_swap from the sandbox_daemon's extract module.

The module is imported as ``sandbox_daemon.extract``, the same package name the
sidecar container uses.
"""

import importlib
import io
import os
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

from tests.common.paths import find_ancestor_containing

_DAEMON_PARENT = (
    find_ancestor_containing("backend/onyx")
    / "backend/onyx/server/features/build/sandbox/image"
)


@pytest.fixture
def extract_mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the daemon module and redirect ALLOWED_PREFIX to tmp_path."""
    monkeypatch.syspath_prepend(str(_DAEMON_PARENT))
    module = importlib.import_module("sandbox_daemon.extract")
    monkeypatch.setattr(module, "ALLOWED_PREFIX", str(tmp_path) + "/")
    return module


def _make_mount_path(tmp_path: Path, name: str = "skills") -> str:
    """Create a mount_path under tmp_path that satisfies ALLOWED_PREFIX."""
    mount = tmp_path / name
    # Parent must exist for .versions dir creation
    mount.parent.mkdir(parents=True, exist_ok=True)
    return str(mount)


def _write_archive(
    tmp_path: Path, members: list[tuple[tarfile.TarInfo, bytes]]
) -> Path:
    archive_path = tmp_path / f"push-{os.urandom(4).hex()}.tar.gz"
    with tarfile.open(archive_path, mode="w:gz") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if info.isreg() else None)
    return archive_path


def _file(name: str, data: bytes, mode: int = 0o644) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = mode
    return info, data


def _entry(
    name: str, entry_type: bytes, linkname: str = ""
) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name=name)
    info.type = entry_type
    info.linkname = linkname
    return info, b""


def _build_tar_gz(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    """Build a tar.gz archive file from a dict of {name: content}."""
    return _write_archive(
        tmp_path, [_file(name, data) for name, data in entries.items()]
    )


def _resolve(mount_path: str) -> Path:
    resolved = Path(os.readlink(mount_path))
    if not resolved.is_absolute():
        resolved = Path(mount_path).parent / resolved
    return resolved


def test_happy_path(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _build_tar_gz(tmp_path, {"hello.txt": b"hello", "sub/deep.txt": b"deep"})

    extract_mod.safe_extract_then_atomic_swap(archive, mount_path)

    assert os.path.islink(mount_path)
    resolved = _resolve(mount_path)
    assert resolved.parent == tmp_path / ".versions" / "skills"
    assert (resolved / "hello.txt").read_bytes() == b"hello"
    assert (resolved / "sub" / "deep.txt").read_bytes() == b"deep"


def test_atomic_swap_replaces_previous(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)

    extract_mod.safe_extract_then_atomic_swap(
        _build_tar_gz(tmp_path, {"v1.txt": b"version1"}), mount_path
    )
    first_target = _resolve(mount_path)

    extract_mod.safe_extract_then_atomic_swap(
        _build_tar_gz(tmp_path, {"v2.txt": b"version2"}), mount_path
    )
    second_target = _resolve(mount_path)

    assert first_target != second_target
    assert (second_target / "v2.txt").read_bytes() == b"version2"
    assert not (second_target / "v1.txt").exists()
    # The previous version stays readable during its grace period.
    assert (first_target / "v1.txt").read_bytes() == b"version1"


def test_next_push_removes_stale_versions_of_same_mount(
    tmp_path: Path, extract_mod: ModuleType
) -> None:
    skills = _make_mount_path(tmp_path, "skills")
    library = _make_mount_path(tmp_path, "user_library")
    extract_mod.safe_extract_then_atomic_swap(
        _build_tar_gz(tmp_path, {"lib.txt": b"lib"}), library
    )
    extract_mod.safe_extract_then_atomic_swap(
        _build_tar_gz(tmp_path, {"a.txt": b"1"}), skills
    )
    first = _resolve(skills)
    extract_mod.safe_extract_then_atomic_swap(
        _build_tar_gz(tmp_path, {"a.txt": b"2"}), skills
    )
    second = _resolve(skills)
    # A tree left by an interrupted extraction.
    orphan = tmp_path / ".versions" / "skills" / "orphan"
    orphan.mkdir()

    extract_mod.safe_extract_then_atomic_swap(
        _build_tar_gz(tmp_path, {"a.txt": b"3"}), skills
    )

    third = _resolve(skills)
    assert sorted(
        p.name for p in (tmp_path / ".versions" / "skills").iterdir()
    ) == sorted([second.name, third.name])
    assert not first.exists()
    assert not orphan.exists()
    assert (third / "a.txt").read_bytes() == b"3"
    assert (_resolve(library) / "lib.txt").read_bytes() == b"lib"


def test_failed_push_keeps_old_tree_and_removes_partial_version(
    tmp_path: Path, extract_mod: ModuleType
) -> None:
    mount_path = _make_mount_path(tmp_path)
    extract_mod.safe_extract_then_atomic_swap(
        _build_tar_gz(tmp_path, {"keep.txt": b"keep"}), mount_path
    )
    live = _resolve(mount_path)
    bad = _write_archive(
        tmp_path,
        [
            _file("ok.txt", b"partial"),
            _entry("link.txt", tarfile.SYMTYPE, "/etc/passwd"),
        ],
    )

    with pytest.raises(ValueError, match="[Ll]ink"):
        extract_mod.safe_extract_then_atomic_swap(bad, mount_path)

    assert _resolve(mount_path) == live
    assert (live / "keep.txt").read_bytes() == b"keep"
    assert list((tmp_path / ".versions" / "skills").iterdir()) == [live]


def test_truncated_archive_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _build_tar_gz(tmp_path, {"a.bin": os.urandom(64 * 1024)})
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])

    with pytest.raises((EOFError, tarfile.TarError)):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)

    assert not os.path.lexists(mount_path)
    assert list((tmp_path / ".versions" / "skills").iterdir()) == []


def test_path_traversal_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _build_tar_gz(tmp_path, {"../escape.txt": b"oops!"})

    with pytest.raises(ValueError, match="[Pp]ath traversal"):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)


def test_symlink_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _write_archive(
        tmp_path, [_entry("link.txt", tarfile.SYMTYPE, "/etc/passwd")]
    )

    with pytest.raises(ValueError, match="[Ll]ink"):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)


def test_absolute_path_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _build_tar_gz(tmp_path, {"/etc/passwd": b"root"})

    # Absolute paths are caught by the path traversal check (normpath resolves
    # them outside bundle_root) before the explicit absolute-path check.
    with pytest.raises(ValueError, match="[Pp]ath traversal|[Aa]bsolute"):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)


def test_oversized_file_rejected(
    tmp_path: Path, extract_mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount_path = _make_mount_path(tmp_path)
    monkeypatch.setattr(extract_mod, "MAX_FILE_BYTES", 50)
    archive = _build_tar_gz(tmp_path, {"big.bin": b"x" * 60})

    with pytest.raises(ValueError, match="too large"):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)


def test_oversized_bundle_rejected(
    tmp_path: Path, extract_mod: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount_path = _make_mount_path(tmp_path)
    monkeypatch.setattr(extract_mod, "MAX_BUNDLE_BYTES", 100)
    archive = _build_tar_gz(tmp_path, {"a.bin": b"x" * 60, "b.bin": b"y" * 60})

    with pytest.raises(ValueError, match="[Tt]otal.*size"):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)


def test_sparse_file_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _write_archive(tmp_path, [_entry("sparse.bin", tarfile.GNUTYPE_SPARSE)])

    with pytest.raises((ValueError, tarfile.TarError)):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)

    assert not os.path.lexists(mount_path)


def test_non_utf8_path_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive_path = tmp_path / "bad.tar.gz"
    with tarfile.open(archive_path, mode="w:gz", errors="surrogateescape") as tar:
        info = tarfile.TarInfo()
        # A surrogate-escaped name fails strict UTF-8 encoding in _validate_member.
        info.name = "bad\udcffname.txt"
        info.size = 3
        tar.addfile(info, io.BytesIO(b"abc"))

    with pytest.raises(ValueError, match="[Nn]on-UTF-8"):
        extract_mod.safe_extract_then_atomic_swap(archive_path, mount_path)


def test_special_file_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _write_archive(tmp_path, [_entry("myfifo", tarfile.FIFOTYPE)])

    with pytest.raises(ValueError, match="[Ss]pecial"):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)


def test_hardlink_rejected(tmp_path: Path, extract_mod: ModuleType) -> None:
    mount_path = _make_mount_path(tmp_path)
    archive = _write_archive(
        tmp_path, [_entry("hard.txt", tarfile.LNKTYPE, "target.txt")]
    )

    with pytest.raises(ValueError, match="[Ll]ink"):
        extract_mod.safe_extract_then_atomic_swap(archive, mount_path)


def test_setuid_and_world_write_bits_stripped(
    tmp_path: Path, extract_mod: ModuleType
) -> None:
    """File modes are masked to 0o755 so setuid/setgid/sticky and group/other-write are stripped."""
    mount_path = _make_mount_path(tmp_path)
    # setuid (4000) + setgid (2000) + sticky (1000) + group/other write (022)
    archive = _write_archive(tmp_path, [_file("dangerous.bin", b"data", 0o7777)])

    extract_mod.safe_extract_then_atomic_swap(archive, mount_path)

    mode = (_resolve(mount_path) / "dangerous.bin").stat().st_mode & 0o7777
    assert mode & 0o7000 == 0
    assert mode & 0o022 == 0
