"""Opencode data archive create/restore helpers for the sandbox sidecar."""

import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
from pathlib import Path

from sandbox_daemon.snapshot import SESSIONS_ROOT
from sandbox_daemon.snapshot import SnapshotError

# Opencode's data home. Defaults to the K8s shared-volume mount; the Docker
# backend execs this module with OPENCODE_DATA_HOME set to its own data home.
OPENCODE_DATA_DIR = Path(
    os.environ.get("OPENCODE_DATA_HOME", "/workspace/opencode-data")
)
OPENCODE_HISTORY_RESTORED_SENTINEL = Path(
    "/workspace/managed/.onyx/opencode-history-restored"
)

_OPENCODE_ARCHIVE_ROOT = ".opencode-data"
_OPENCODE_DB_RELATIVE_PATH = Path("opencode/opencode.db")
_SQLITE_MAGIC = b"SQLite format 3\x00"
_OPENCODE_HISTORY_RESTORE_LOCK = threading.RLock()


def _safe_opencode_data_dir(*, create: bool) -> Path:
    workspace_root = SESSIONS_ROOT.parent.resolve()
    if OPENCODE_DATA_DIR.is_symlink():
        raise SnapshotError("opencode data dir is a symlink; refusing access")

    if create:
        OPENCODE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    if OPENCODE_DATA_DIR.exists() and not OPENCODE_DATA_DIR.is_dir():
        raise SnapshotError("opencode data path is not a directory")

    try:
        OPENCODE_DATA_DIR.resolve(strict=False).relative_to(workspace_root)
    except ValueError as e:
        raise SnapshotError("opencode data path escapes workspace root") from e
    return OPENCODE_DATA_DIR


def _remove_file_or_tree(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _backup_sqlite_db(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    src: sqlite3.Connection | None = None
    dst: sqlite3.Connection | None = None
    try:
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        dst = sqlite3.connect(destination)
        src.execute("PRAGMA busy_timeout = 5000")
        dst.execute("PRAGMA busy_timeout = 5000")
        src.backup(dst)
    except sqlite3.Error as e:
        raise SnapshotError(f"opencode sqlite backup failed: {e}") from e
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()


def _snapshot_sqlite_db_if_present(data_dir: Path, staged_root: Path) -> None:
    source_db = data_dir / _OPENCODE_DB_RELATIVE_PATH
    if not source_db.exists():
        return
    if source_db.is_symlink() or not source_db.is_file():
        return

    staged_db = staged_root / _OPENCODE_DB_RELATIVE_PATH
    _remove_file_or_tree(staged_db)
    for suffix in ("-wal", "-shm"):
        _remove_file_or_tree(staged_db.with_name(f"{staged_db.name}{suffix}"))
    _backup_sqlite_db(source_db, staged_db)


def create_opencode_history_archive_file() -> Path | None:
    """Create a local tarball of opencode data, or None when it has no content."""
    with _OPENCODE_HISTORY_RESTORE_LOCK:
        data_dir = _safe_opencode_data_dir(create=False)
        if not data_dir.exists() or not any(data_dir.iterdir()):
            return None

        tmp_path: Path | None = None
        with tempfile.TemporaryDirectory(prefix=".opencode-history-create-") as tmp_dir:
            staging_path = Path(tmp_dir)
            staged_root = staging_path / _OPENCODE_ARCHIVE_ROOT
            shutil.copytree(data_dir, staged_root, symlinks=True)
            _snapshot_sqlite_db_if_present(data_dir, staged_root)

            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".tar.gz", delete=False
                ) as tmp_file:
                    tmp_path = Path(tmp_file.name)

                with tarfile.open(tmp_path, "w:gz", compresslevel=6) as tar:
                    tar.add(staged_root, arcname=_OPENCODE_ARCHIVE_ROOT, recursive=True)
            except Exception:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
                raise

        return tmp_path


def mark_opencode_history_restored() -> None:
    """Mark startup history restore complete for the restartable init sidecar."""
    with _OPENCODE_HISTORY_RESTORE_LOCK:
        marker_parent = OPENCODE_HISTORY_RESTORED_SENTINEL.parent
        marker_parent.mkdir(parents=True, exist_ok=True)
        OPENCODE_HISTORY_RESTORED_SENTINEL.touch(mode=0o600, exist_ok=True)


def opencode_history_restored() -> bool:
    """Return True once startup history restore can release the sandbox."""
    return OPENCODE_HISTORY_RESTORED_SENTINEL.is_file()


def _extract_archive_to_staging(archive_path: Path, staging_path: Path) -> Path:
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(staging_path, filter="data")

    restored_root = staging_path / _OPENCODE_ARCHIVE_ROOT
    if restored_root.is_symlink() or not restored_root.is_dir():
        raise SnapshotError("opencode history archive is missing opencode data")
    return restored_root


def _clear_directory_contents(directory: Path, *, preserve: Path | None = None) -> None:
    for child in directory.iterdir():
        if child == preserve:
            continue
        _remove_file_or_tree(child)


def _replace_opencode_data_contents(
    data_dir: Path,
    restored_root: Path,
    staging_path: Path,
) -> None:
    _clear_directory_contents(data_dir, preserve=staging_path)
    for child in restored_root.iterdir():
        os.replace(child, data_dir / child.name)


def _opencode_db_is_healthy(data_dir: Path) -> bool:
    db_path = data_dir / _OPENCODE_DB_RELATIVE_PATH
    if not db_path.exists():
        return True
    if db_path.is_symlink() or not db_path.is_file():
        return False

    try:
        with db_path.open("rb") as db_file:
            if db_file.read(len(_SQLITE_MAGIC)) != _SQLITE_MAGIC:
                return False

        conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
        try:
            result = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return False

    return result is not None and result[0] == "ok"


def restore_opencode_history_archive(archive_path: Path) -> None:
    """Restore opencode's data directory from a sidecar-local archive."""
    with _OPENCODE_HISTORY_RESTORE_LOCK:
        if opencode_history_restored():
            return

        data_dir = _safe_opencode_data_dir(create=True)

        try:
            with tempfile.TemporaryDirectory(
                dir=data_dir,
                prefix=".opencode-history-restore-",
            ) as tmp_dir:
                staging_path = Path(tmp_dir)
                restored_root = _extract_archive_to_staging(archive_path, staging_path)

                data_dir = _safe_opencode_data_dir(create=False)
                _replace_opencode_data_contents(data_dir, restored_root, staging_path)
                if not _opencode_db_is_healthy(data_dir):
                    _clear_directory_contents(data_dir, preserve=staging_path)
                mark_opencode_history_restored()
        except (tarfile.TarError, OSError) as e:
            raise SnapshotError(f"invalid opencode history archive: {e}") from e
