import io
import os
import tarfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from onyx.connectors.cross_connector_utils import repo_snapshot
from onyx.connectors.cross_connector_utils.repo_snapshot import (
    RepoSnapshotError,
    get_or_create_snapshot,
    read_snapshot_file,
    walk_snapshot_files,
)


@pytest.fixture(autouse=True)
def isolated_cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_snapshot, "_CACHE_ROOT", tmp_path / "snapshot_cache")


def _make_tarball(files: dict[str, bytes], top_dir: str = "org-repo-abc1234") -> bytes:
    """A repo-archive-shaped tar.gz: contents wrapped in one top-level dir."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            info = tarfile.TarInfo(name=f"{top_dir}/{path}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


FILES = {
    "src/main.py": b"def main():\n    return 1\n",
    "README.md": b"# Hello\n",
}


def test_snapshot_extract_walk_and_read() -> None:
    fetch = MagicMock(return_value=_make_tarball(FILES))
    root = get_or_create_snapshot("github\norg/repo\nmain", fetch)

    files = dict(walk_snapshot_files(root))
    assert set(files) == {"src/main.py", "README.md"}
    assert files["src/main.py"] == len(FILES["src/main.py"])

    content = read_snapshot_file(root, "src/main.py", max_size_bytes=1_000_000)
    assert content == FILES["src/main.py"]


def test_second_call_uses_cache_without_fetching() -> None:
    fetch = MagicMock(return_value=_make_tarball(FILES))
    first = get_or_create_snapshot("k", fetch)
    second = get_or_create_snapshot("k", fetch)

    assert first == second
    fetch.assert_called_once()


def test_malicious_archive_members_are_rejected() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="top/../../escape.txt")
        payload = b"boom"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(RepoSnapshotError):
        get_or_create_snapshot("evil", MagicMock(return_value=buf.getvalue()))


def test_read_rejects_escapes_and_oversize() -> None:
    root = get_or_create_snapshot("k2", MagicMock(return_value=_make_tarball(FILES)))

    with pytest.raises(RepoSnapshotError):
        read_snapshot_file(root, "../outside.txt", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError):
        read_snapshot_file(root, "src/main.py", max_size_bytes=5)


def test_stale_snapshots_are_pruned() -> None:
    root = get_or_create_snapshot("k3", MagicMock(return_value=_make_tarball(FILES)))
    old = time.time() - repo_snapshot._SNAPSHOT_TTL_SECONDS - 60
    os.utime(root, (old, old))
    repo_snapshot._prune_stale_snapshots()
    assert not root.exists()


# --- Extraction resource limits -----------------------------------------------------


def test_member_count_cap_rejects_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_snapshot, "_MAX_ARCHIVE_MEMBERS", 1)

    with pytest.raises(RepoSnapshotError, match="members"):
        get_or_create_snapshot("cap1", MagicMock(return_value=_make_tarball(FILES)))


def test_total_size_cap_rejects_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_snapshot, "_MAX_EXTRACTED_BYTES", 10)

    with pytest.raises(RepoSnapshotError, match="extracted bytes"):
        get_or_create_snapshot("cap2", MagicMock(return_value=_make_tarball(FILES)))


# --- Symlink defenses ----------------------------------------------------------------


def test_symlink_top_level_entry_is_not_promoted_to_root() -> None:
    """An archive whose only top-level member is a symlink must not have the
    symlink published as the snapshot root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="link")
        info.type = tarfile.SYMTYPE
        info.linkname = "."
        tar.addfile(info)

    root = get_or_create_snapshot("sym-root", MagicMock(return_value=buf.getvalue()))

    # The snapshot root is the staging dir itself, holding the symlink as a
    # plain member; walking yields no regular files.
    assert not root.is_symlink()
    assert dict(walk_snapshot_files(root)) == {}


def test_read_rejects_symlink_path_component() -> None:
    root = get_or_create_snapshot(
        "sym-read", MagicMock(return_value=_make_tarball(FILES))
    )
    # A symlink inside the snapshot pointing at a sibling directory must be
    # refused before resolve() would silently follow it.
    (root / "sneaky").symlink_to(root.parent)

    with pytest.raises(RepoSnapshotError, match="Symlink"):
        read_snapshot_file(root, "sneaky/anything.txt", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="Symlink"):
        read_snapshot_file(root, "sneaky", max_size_bytes=1_000_000)
