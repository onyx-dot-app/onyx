import hashlib
import io
import os
import shutil
import tarfile
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from onyx.repo_archives import snapshot
from onyx.repo_archives.models import RepoArchive, RepoRevision
from onyx.repo_archives.snapshot import RepoSnapshotError, get_or_create_snapshot
from tests.utils.repo_archives import make_repo_tarball, revision


@pytest.fixture(autouse=True)
def isolated_cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot, "_CACHE_ROOT", tmp_path / "snapshot_cache")


def _rev(tag: str) -> RepoRevision:
    """A distinct revision per test scenario."""
    return revision(hashlib.sha256(tag.encode()).hexdigest()[:40])


def _opener(tmp_path: Path, archive: bytes, rev: RepoRevision) -> MagicMock:
    """An `open_archive` callable serving `archive` from disk; call-countable."""
    path = tmp_path / f"{rev.commit_sha}.tar.gz"
    path.write_bytes(archive)
    return MagicMock(
        side_effect=lambda: nullcontext(
            RepoArchive(path=path, size=len(archive), revision=rev)
        )
    )


FILES = {
    "src/main.py": b"def main():\n    return 1\n",
    "README.md": b"# Hello\n",
}


def test_snapshot_extract_walk_and_read(tmp_path: Path) -> None:
    rev = _rev("basic")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))

    assert snap.revision == rev
    files = dict(snap.walk_files())
    assert set(files) == {"src/main.py", "README.md"}
    assert files["src/main.py"] == len(FILES["src/main.py"])
    assert (
        snap.read_file("src/main.py", max_size_bytes=1_000_000) == FILES["src/main.py"]
    )


def test_second_call_uses_cache_without_fetching(tmp_path: Path) -> None:
    rev = _rev("k")
    opener = _opener(tmp_path, make_repo_tarball(FILES), rev)
    first = get_or_create_snapshot(rev, opener)
    second = get_or_create_snapshot(rev, opener)

    assert first.root == second.root
    opener.assert_called_once()


def test_archive_without_wrapper_dir_is_served_from_tree_root(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in ("a.txt", "b.txt"):
            info = tarfile.TarInfo(name=name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))

    rev = _rev("flat")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, buf.getvalue(), rev))
    assert set(dict(snap.walk_files())) == {"a.txt", "b.txt"}


def test_fetch_errors_propagate_and_leave_no_snapshot() -> None:
    class FetchBoom(Exception):
        pass

    with pytest.raises(FetchBoom):
        get_or_create_snapshot(_rev("fetch-fail"), MagicMock(side_effect=FetchBoom()))
    assert list(snapshot._CACHE_ROOT.iterdir()) == []


def test_malicious_archive_members_are_rejected(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="top/../../escape.txt")
        payload = b"boom"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    rev = _rev("evil")
    with pytest.raises(RepoSnapshotError):
        get_or_create_snapshot(rev, _opener(tmp_path, buf.getvalue(), rev))


def test_empty_archive_is_rejected_and_not_cached(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="org-repo-abc1234")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)

    rev = _rev("empty")
    with pytest.raises(RepoSnapshotError, match="no files"):
        get_or_create_snapshot(rev, _opener(tmp_path, buf.getvalue(), rev))
    assert list(snapshot._CACHE_ROOT.iterdir()) == []


def test_read_rejects_escapes_missing_and_oversize(tmp_path: Path) -> None:
    rev = _rev("k2")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))

    with pytest.raises(RepoSnapshotError, match="escapes"):
        snap.read_file("../outside.txt", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="escapes"):
        snap.read_file("/etc/passwd", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="Cannot read"):
        snap.read_file("src/missing.py", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="Not a regular file"):
        snap.read_file("src", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="size cap"):
        snap.read_file("src/main.py", max_size_bytes=5)


def test_stale_snapshots_are_pruned(tmp_path: Path) -> None:
    rev = _rev("k3")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))
    old = time.time() - snapshot.REPO_SNAPSHOT_TTL_SECONDS - 60
    os.utime(snap.root, (old, old))
    snapshot._prune_stale_snapshots()
    assert not snap.root.exists()


# --- Concurrency ---------------------------------------------------------------------


def test_concurrent_miss_publishes_once_and_returns_winner(tmp_path: Path) -> None:
    """A second worker publishes the same revision while our fetch is in
    flight. os.replace onto the non-empty winner fails; that is a success,
    not an error, and the caller sees the winner's snapshot."""
    rev = _rev("race")
    winner = _opener(tmp_path, make_repo_tarball({"README.md": b"winner\n"}), rev)
    loser_path = tmp_path / "loser.tar.gz"
    loser_path.write_bytes(make_repo_tarball({"README.md": b"loser\n"}))

    def _open_loser() -> nullcontext[RepoArchive]:
        get_or_create_snapshot(rev, winner)
        return nullcontext(RepoArchive(path=loser_path, size=1, revision=rev))

    snap = get_or_create_snapshot(rev, _open_loser)

    assert snap.read_file("README.md", max_size_bytes=100) == b"winner\n"
    assert [p.name for p in snapshot._CACHE_ROOT.iterdir()] == [snap.root.name]


def test_walk_raises_when_snapshot_removed_mid_walk(tmp_path: Path) -> None:
    rev = _rev("gone")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))
    walk = snap.walk_files()
    next(walk)
    shutil.rmtree(snap.root)

    with pytest.raises(RepoSnapshotError, match="walk failed"):
        list(walk)


def test_walk_raises_when_snapshot_missing(tmp_path: Path) -> None:
    rev = _rev("gone2")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))
    shutil.rmtree(snap.root)

    with pytest.raises(RepoSnapshotError, match="missing"):
        list(snap.walk_files())


def test_cache_hit_raced_by_prune_refetches(tmp_path: Path) -> None:
    rev = _rev("pruned")
    opener = _opener(tmp_path, make_repo_tarball(FILES), rev)
    snap = get_or_create_snapshot(rev, opener)
    real_utime = os.utime

    def _utime_then_vanish(
        path: str | Path, times: tuple[float, float] | None = None
    ) -> None:
        if Path(path) == snap.root:
            shutil.rmtree(snap.root)
        real_utime(path, times)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(snapshot.os, "utime", _utime_then_vanish)
        again = get_or_create_snapshot(rev, opener)

    assert opener.call_count == 2
    assert again.root == snap.root
    assert dict(again.walk_files()) == {p: len(c) for p, c in FILES.items()}


# --- Extraction resource limits -----------------------------------------------------


def test_member_count_cap_rejects_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot, "REPO_SNAPSHOT_MAX_ARCHIVE_MEMBERS", 1)
    rev = _rev("cap1")
    with pytest.raises(RepoSnapshotError, match="members"):
        get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))


def test_total_size_cap_rejects_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot, "REPO_SNAPSHOT_MAX_EXTRACTED_BYTES", 10)
    rev = _rev("cap2")
    with pytest.raises(RepoSnapshotError, match="extracted bytes"):
        get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))


# --- Symlink defenses ----------------------------------------------------------------


def _symlink_tarball(with_file: bool) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        link = tarfile.TarInfo(name="link")
        link.type = tarfile.SYMTYPE
        link.linkname = "."
        tar.addfile(link)
        if with_file:
            info = tarfile.TarInfo(name="README.md")
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    return buf.getvalue()


def test_symlink_top_level_entry_is_not_promoted_to_root(tmp_path: Path) -> None:
    """A symlink posing as the archive's wrapper directory must not be
    published as the snapshot root."""
    rev = _rev("sym-root")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, _symlink_tarball(True), rev))

    assert not snap.root.is_symlink()
    assert dict(snap.walk_files()) == {"README.md": 1}


def test_symlink_only_archive_is_rejected(tmp_path: Path) -> None:
    rev = _rev("sym-only")
    with pytest.raises(RepoSnapshotError, match="no files"):
        get_or_create_snapshot(rev, _opener(tmp_path, _symlink_tarball(False), rev))


def test_read_refuses_symlink_escaping_root_but_allows_internal(
    tmp_path: Path,
) -> None:
    rev = _rev("sym-read")
    snap = get_or_create_snapshot(rev, _opener(tmp_path, make_repo_tarball(FILES), rev))
    (snap.root / "sneaky").symlink_to(snap.root.parent)
    (snap.root / "alias.md").symlink_to("README.md")

    with pytest.raises(RepoSnapshotError, match="escapes"):
        snap.read_file("sneaky/anything.txt", max_size_bytes=1_000_000)
    with pytest.raises(RepoSnapshotError, match="escapes"):
        snap.read_file("sneaky", max_size_bytes=1_000_000)
    # An in-repo symlink to a file stays inside the root and is readable.
    assert snap.read_file("alias.md", max_size_bytes=1_000_000) == FILES["README.md"]
    # Walks report only regular files; symlinks are never yielded.
    assert "alias.md" not in dict(snap.walk_files())
