import io
import os
import shutil
import tarfile
import time
from pathlib import Path
from typing import BinaryIO
from unittest.mock import MagicMock

import pytest

from onyx.connectors.cross_connector_utils import repo_snapshot
from onyx.connectors.cross_connector_utils.repo_snapshot import (
    RepoSnapshotError,
    get_or_create_snapshot,
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


def _fetcher(archive: bytes) -> MagicMock:
    """A `fetch_archive` callable that streams `archive` into the sink."""
    return MagicMock(side_effect=lambda sink: sink.write(archive))


FILES = {
    "src/main.py": b"def main():\n    return 1\n",
    "README.md": b"# Hello\n",
}


def test_snapshot_extract_walk_and_read() -> None:
    fetch = _fetcher(_make_tarball(FILES))
    snapshot = get_or_create_snapshot("github\norg/repo\nmain", fetch)

    files = dict(snapshot.walk_files())
    assert set(files) == {"src/main.py", "README.md"}
    assert files["src/main.py"] == len(FILES["src/main.py"])

    content = snapshot.read_file("src/main.py", max_size_bytes=1_000_000)
    assert content == FILES["src/main.py"]


def test_second_call_uses_cache_without_fetching() -> None:
    fetch = _fetcher(_make_tarball(FILES))
    first = get_or_create_snapshot("k", fetch)
    second = get_or_create_snapshot("k", fetch)

    assert first.root == second.root
    fetch.assert_called_once()


def test_archive_without_wrapper_dir_is_served_from_tree_root() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("a.txt", "b.txt"):
            info = tarfile.TarInfo(name=name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))

    snapshot = get_or_create_snapshot("flat", _fetcher(buf.getvalue()))
    assert set(dict(snapshot.walk_files())) == {"a.txt", "b.txt"}


def test_fetch_errors_propagate_and_leave_no_snapshot() -> None:
    class FetchBoom(Exception):
        pass

    def _fetch(_sink: BinaryIO) -> None:
        raise FetchBoom()

    with pytest.raises(FetchBoom):
        get_or_create_snapshot("fetch-fail", _fetch)
    assert list(repo_snapshot._CACHE_ROOT.iterdir()) == []


def test_malicious_archive_members_are_rejected() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="top/../../escape.txt")
        payload = b"boom"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(RepoSnapshotError):
        get_or_create_snapshot("evil", _fetcher(buf.getvalue()))


def test_empty_archive_is_rejected_and_not_cached() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="org-repo-abc1234")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)

    with pytest.raises(RepoSnapshotError, match="no files"):
        get_or_create_snapshot("empty", _fetcher(buf.getvalue()))
    assert list(repo_snapshot._CACHE_ROOT.iterdir()) == []


def test_read_rejects_escapes_missing_and_oversize() -> None:
    snapshot = get_or_create_snapshot("k2", _fetcher(_make_tarball(FILES)))

    with pytest.raises(RepoSnapshotError, match="escapes"):
        snapshot.read_file("../outside.txt", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="escapes"):
        snapshot.read_file("/etc/passwd", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="Cannot read"):
        snapshot.read_file("src/missing.py", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="Not a regular file"):
        snapshot.read_file("src", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="size cap"):
        snapshot.read_file("src/main.py", max_size_bytes=5)


def test_stale_snapshots_are_pruned() -> None:
    snapshot = get_or_create_snapshot("k3", _fetcher(_make_tarball(FILES)))
    old = time.time() - repo_snapshot.REPO_SNAPSHOT_TTL_SECONDS - 60
    os.utime(snapshot.root, (old, old))
    repo_snapshot._prune_stale_snapshots()
    assert not snapshot.root.exists()


# --- Concurrency ---------------------------------------------------------------------


def test_concurrent_miss_publishes_once_and_returns_winner() -> None:
    """A second worker publishes the same key while our fetch is in flight.
    os.replace onto the non-empty winner fails; that is a success, not an
    error, and the caller sees the winner's snapshot."""
    winner_files = {"README.md": b"winner\n"}
    loser_files = {"README.md": b"loser\n"}

    def _fetch(sink: BinaryIO) -> None:
        get_or_create_snapshot("race", _fetcher(_make_tarball(winner_files)))
        sink.write(_make_tarball(loser_files))

    snapshot = get_or_create_snapshot("race", _fetch)

    assert snapshot.read_file("README.md", max_size_bytes=100) == b"winner\n"
    assert [p.name for p in repo_snapshot._CACHE_ROOT.iterdir()] == [snapshot.root.name]


def test_walk_raises_when_snapshot_removed_mid_walk() -> None:
    snapshot = get_or_create_snapshot("gone", _fetcher(_make_tarball(FILES)))
    walk = snapshot.walk_files()
    next(walk)
    shutil.rmtree(snapshot.root)

    with pytest.raises(RepoSnapshotError, match="walk failed"):
        list(walk)


def test_walk_raises_when_snapshot_missing() -> None:
    snapshot = get_or_create_snapshot("gone2", _fetcher(_make_tarball(FILES)))
    shutil.rmtree(snapshot.root)

    with pytest.raises(RepoSnapshotError, match="missing"):
        list(snapshot.walk_files())


def test_cache_hit_raced_by_prune_refetches() -> None:
    snapshot = get_or_create_snapshot("pruned", _fetcher(_make_tarball(FILES)))
    real_utime = os.utime

    def _utime_then_vanish(
        path: str | Path, times: tuple[float, float] | None = None
    ) -> None:
        if Path(path) == snapshot.root:
            shutil.rmtree(snapshot.root)
        real_utime(path, times)

    fetch = _fetcher(_make_tarball(FILES))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(repo_snapshot.os, "utime", _utime_then_vanish)
        again = get_or_create_snapshot("pruned", fetch)

    fetch.assert_called_once()
    assert again.root == snapshot.root
    assert dict(again.walk_files()) == {p: len(c) for p, c in FILES.items()}


# --- Extraction resource limits -----------------------------------------------------


def test_member_count_cap_rejects_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_snapshot, "REPO_SNAPSHOT_MAX_ARCHIVE_MEMBERS", 1)

    with pytest.raises(RepoSnapshotError, match="members"):
        get_or_create_snapshot("cap1", _fetcher(_make_tarball(FILES)))


def test_total_size_cap_rejects_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo_snapshot, "REPO_SNAPSHOT_MAX_EXTRACTED_BYTES", 10)

    with pytest.raises(RepoSnapshotError, match="extracted bytes"):
        get_or_create_snapshot("cap2", _fetcher(_make_tarball(FILES)))


# --- Symlink defenses ----------------------------------------------------------------


def test_symlink_top_level_entry_is_not_promoted_to_root() -> None:
    """A symlink posing as the archive's wrapper directory must not be
    published as the snapshot root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        link = tarfile.TarInfo(name="link")
        link.type = tarfile.SYMTYPE
        link.linkname = "."
        tar.addfile(link)
        info = tarfile.TarInfo(name="README.md")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))

    snapshot = get_or_create_snapshot("sym-root", _fetcher(buf.getvalue()))

    assert not snapshot.root.is_symlink()
    assert dict(snapshot.walk_files()) == {"README.md": 1}


def test_symlink_only_archive_is_rejected() -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        link = tarfile.TarInfo(name="link")
        link.type = tarfile.SYMTYPE
        link.linkname = "."
        tar.addfile(link)

    with pytest.raises(RepoSnapshotError, match="no files"):
        get_or_create_snapshot("sym-only", _fetcher(buf.getvalue()))


def test_read_refuses_symlink_escaping_root_but_allows_internal() -> None:
    snapshot = get_or_create_snapshot("sym-read", _fetcher(_make_tarball(FILES)))
    (snapshot.root / "sneaky").symlink_to(snapshot.root.parent)
    (snapshot.root / "alias.md").symlink_to("README.md")

    with pytest.raises(RepoSnapshotError, match="escapes"):
        snapshot.read_file("sneaky/anything.txt", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="escapes"):
        snapshot.read_file("sneaky", max_size_bytes=1_000_000)
    # An in-repo symlink to a file stays inside the root and is readable.
    assert (
        snapshot.read_file("alias.md", max_size_bytes=1_000_000) == FILES["README.md"]
    )
    # Walks report only regular files; symlinks are never yielded.
    assert "alias.md" not in dict(snapshot.walk_files())
