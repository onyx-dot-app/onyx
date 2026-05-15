"""Tests for safe_extract_then_atomic_swap from the push daemon's extract module."""

import io
import os
import tarfile
from pathlib import Path

import pytest

from onyx.server.features.build.sandbox.kubernetes.docker.daemon.extract import (
    safe_extract_then_atomic_swap,
)


@pytest.fixture(autouse=True)
def _patch_allowed_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect ALLOWED_PREFIX to tmp_path so tests can write to it."""
    prefix = str(tmp_path) + "/"
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.kubernetes.docker.daemon.extract.ALLOWED_PREFIX",
        prefix,
    )


def _make_mount_path(tmp_path: Path, name: str = "skills") -> str:
    """Create a mount_path under tmp_path that satisfies ALLOWED_PREFIX."""
    mount = tmp_path / name
    # Parent must exist for .versions dir creation
    mount.parent.mkdir(parents=True, exist_ok=True)
    return str(mount)


def _build_tar_gz(entries: dict[str, bytes]) -> bytes:
    """Build a tar.gz archive from a dict of {name: content}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_happy_path(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)
    tar_gz = _build_tar_gz({"hello.txt": b"hello", "sub/deep.txt": b"deep"})

    safe_extract_then_atomic_swap(tar_gz, mount_path)

    # mount_path should be a symlink now
    assert os.path.islink(mount_path)
    resolved = Path(os.readlink(mount_path))
    if not resolved.is_absolute():
        resolved = Path(mount_path).parent / resolved

    assert (resolved / "hello.txt").read_bytes() == b"hello"
    assert (resolved / "sub" / "deep.txt").read_bytes() == b"deep"


def test_atomic_swap_replaces_previous(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)

    tar1 = _build_tar_gz({"v1.txt": b"version1"})
    safe_extract_then_atomic_swap(tar1, mount_path)

    # Resolve first version
    first_target = os.readlink(mount_path)
    if not os.path.isabs(first_target):
        first_target = str(Path(mount_path).parent / first_target)

    tar2 = _build_tar_gz({"v2.txt": b"version2"})
    safe_extract_then_atomic_swap(tar2, mount_path)

    # Should now point to a different version directory
    second_target = os.readlink(mount_path)
    if not os.path.isabs(second_target):
        second_target = str(Path(mount_path).parent / second_target)
    assert first_target != second_target

    # New content should be available
    resolved = Path(second_target)
    assert (resolved / "v2.txt").read_bytes() == b"version2"
    assert not (resolved / "v1.txt").exists()


def test_path_traversal_rejected(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="../escape.txt")
        info.size = 5
        tar.addfile(info, io.BytesIO(b"oops!"))
    tar_gz = buf.getvalue()

    with pytest.raises(ValueError, match="[Pp]ath traversal"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_symlink_rejected(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="link.txt")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    tar_gz = buf.getvalue()

    with pytest.raises(ValueError, match="[Ll]ink"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_absolute_path_rejected(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="/etc/passwd")
        info.size = 4
        tar.addfile(info, io.BytesIO(b"root"))
    tar_gz = buf.getvalue()

    # Absolute paths are caught by the path traversal check (normpath resolves
    # them outside bundle_root) before the explicit absolute-path check.
    with pytest.raises(ValueError, match="[Pp]ath traversal|[Aa]bsolute"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_oversized_file_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount_path = _make_mount_path(tmp_path)

    # Lower MAX_FILE_BYTES so we don't need to create a 25 MiB payload
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.kubernetes.docker.daemon.extract.MAX_FILE_BYTES",
        50,
    )

    # Create a file that exceeds the lowered limit
    tar_gz = _build_tar_gz({"big.bin": b"x" * 60})

    with pytest.raises(ValueError, match="too large"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_oversized_bundle_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount_path = _make_mount_path(tmp_path)

    # Lower the bundle limit for a fast test
    monkeypatch.setattr(
        "onyx.server.features.build.sandbox.kubernetes.docker.daemon.extract.MAX_BUNDLE_BYTES",
        100,
    )

    # Two files that together exceed 100 bytes
    tar_gz = _build_tar_gz({"a.bin": b"x" * 60, "b.bin": b"y" * 60})

    with pytest.raises(ValueError, match="[Tt]otal.*size"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_non_utf8_path_rejected(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo()
        # Assign a name that will fail .encode("utf-8") inside _validate_member.
        # TarInfo.name is a str, but we can give it a surrogate-escaped string
        # which will fail strict UTF-8 encoding.
        info.name = "bad\udcffname.txt"
        info.size = 3
        tar.addfile(info, io.BytesIO(b"abc"))
    tar_gz = buf.getvalue()

    with pytest.raises(ValueError, match="[Nn]on-UTF-8"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_special_file_rejected(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        # Create a FIFO entry
        info = tarfile.TarInfo(name="myfifo")
        info.type = tarfile.FIFOTYPE
        info.size = 0
        tar.addfile(info)
    tar_gz = buf.getvalue()

    with pytest.raises(ValueError, match="[Ss]pecial"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_hardlink_rejected(tmp_path: Path) -> None:
    mount_path = _make_mount_path(tmp_path)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="hard.txt")
        info.type = tarfile.LNKTYPE
        info.linkname = "target.txt"
        tar.addfile(info)
    tar_gz = buf.getvalue()

    with pytest.raises(ValueError, match="[Ll]ink"):
        safe_extract_then_atomic_swap(tar_gz, mount_path)


def test_setuid_and_world_write_bits_stripped(tmp_path: Path) -> None:
    """File modes are masked to 0o755 so setuid/setgid/sticky and group/other-write are stripped."""
    mount_path = _make_mount_path(tmp_path)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="dangerous.bin")
        info.size = 4
        # setuid (4000) + setgid (2000) + sticky (1000) + group/other write (022)
        info.mode = 0o7777
        tar.addfile(info, io.BytesIO(b"data"))
    tar_gz = buf.getvalue()

    safe_extract_then_atomic_swap(tar_gz, mount_path)

    resolved = Path(os.readlink(mount_path))
    if not resolved.is_absolute():
        resolved = Path(mount_path).parent / resolved

    mode = (resolved / "dangerous.bin").stat().st_mode & 0o7777
    # setuid/setgid/sticky must be stripped
    assert mode & 0o7000 == 0
    # group/other write must be stripped
    assert mode & 0o022 == 0
