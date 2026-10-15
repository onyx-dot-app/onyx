"""OpenCode history archive operations, always run as the sandbox user."""

import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
from pathlib import Path

from .models import MAX_HISTORY_ARCHIVE_BYTES
from .snapshot import SESSIONS_ROOT, SnapshotError

OPENCODE_DATA_DIR = Path("/workspace/opencode-data")

_OPENCODE_ARCHIVE_ROOT = ".opencode-data"
_OPENCODE_DB_RELATIVE_PATH = Path("opencode/opencode.db")
_SQLITE_MAGIC = b"SQLite format 3\x00"
_OPENCODE_HISTORY_RESTORE_LOCK = threading.RLock()
MAX_HISTORY_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
MAX_HISTORY_ARCHIVE_MEMBERS = 100_000


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
                if tmp_path.stat().st_size > MAX_HISTORY_ARCHIVE_BYTES:
                    raise SnapshotError(
                        "OpenCode history compressed archive exceeds 1 GiB limit"
                    )
                with tarfile.open(tmp_path, "r:gz") as tar:
                    _validated_history_members(tar)
            except Exception:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)
                raise

        return tmp_path


def _validated_history_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members: list[tarfile.TarInfo] = []
    uncompressed_bytes = 0
    for member in tar:
        if len(members) >= MAX_HISTORY_ARCHIVE_MEMBERS:
            raise SnapshotError("OpenCode history archive exceeds member count limit")
        members.append(member)
        if not (member.isfile() or member.isdir()):
            raise SnapshotError(
                "OpenCode history archive member is not a file or directory: "
                f"{member.name}"
            )
        name = os.path.normpath(member.name)
        if (
            member.name.startswith("/")
            or ".." in member.name.split("/")
            or (
                name != _OPENCODE_ARCHIVE_ROOT
                and not name.startswith(f"{_OPENCODE_ARCHIVE_ROOT}/")
            )
        ):
            raise SnapshotError(
                "OpenCode history archive member escapes "
                f"{_OPENCODE_ARCHIVE_ROOT}: {member.name}"
            )
        if member.isfile():
            uncompressed_bytes += member.size
            if uncompressed_bytes > MAX_HISTORY_UNCOMPRESSED_BYTES:
                raise SnapshotError(
                    "OpenCode history expanded archive exceeds 4 GiB limit"
                )
    return members


def _extract_archive_to_staging(archive_path: Path, staging_path: Path) -> Path:
    if archive_path.stat().st_size > MAX_HISTORY_ARCHIVE_BYTES:
        raise SnapshotError("OpenCode history compressed archive exceeds 1 GiB limit")
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            members = _validated_history_members(tar)
            tar.extractall(staging_path, members=members, filter="data")
    except (tarfile.TarError, EOFError) as error:
        raise SnapshotError(
            f"OpenCode history archive is unreadable: {error}"
        ) from error

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
    """Restore OpenCode's data directory from a local archive."""
    with _OPENCODE_HISTORY_RESTORE_LOCK:
        data_dir = _safe_opencode_data_dir(create=True)

        try:
            with tempfile.TemporaryDirectory(
                dir=data_dir,
                prefix=".opencode-history-restore-",
            ) as tmp_dir:
                staging_path = Path(tmp_dir)
                restored_root = _extract_archive_to_staging(archive_path, staging_path)

                if not _opencode_db_is_healthy(restored_root):
                    raise SnapshotError("OpenCode history database is corrupt")
                data_dir = _safe_opencode_data_dir(create=False)
                _replace_opencode_data_contents(data_dir, restored_root, staging_path)
        except (tarfile.TarError, OSError) as e:
            raise SnapshotError(f"invalid opencode history archive: {e}") from e
