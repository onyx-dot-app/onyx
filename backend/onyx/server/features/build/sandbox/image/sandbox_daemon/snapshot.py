"""Snapshot create/restore operations for the sandbox sidecar.

The sidecar owns pod-local filesystem access. The api-server owns durable
storage by streaming these tarballs into/out of the main Onyx FileStore.
"""

import logging
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

SESSIONS_ROOT = Path("/workspace/sessions")
# Must match onyx.server.features.build.sandbox.base.BUN_CACHE_DIR -- the
# daemon can't import from the main package at runtime, hence the copy.
BUN_CACHE_DIR = SESSIONS_ROOT / ".bun-cache"
BUN_IMAGE_CACHE_DIR = Path("/home/sandbox/.bun/install/cache")
logger = logging.getLogger(__name__)


class SnapshotError(RuntimeError):
    """Raised when tar or bun fails so the manager can see the cause."""


_SNAPSHOT_ROOTS = frozenset({"outputs", "attachments"})
_SNAPSHOT_GENERATED_DIR_NAMES = frozenset({"node_modules", ".next"})
MAX_SNAPSHOT_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_SNAPSHOT_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
_ARCHIVE_CHUNK_BYTES = 1024 * 1024
_SKIPPED_PATH_LOG_SAMPLE_LIMIT = 20


def _safe_session_path(session_id: UUID, *, create: bool) -> Path:
    """Return the pod-local session path, rejecting symlink escape hatches."""
    sessions_root = SESSIONS_ROOT.resolve()
    session_path = SESSIONS_ROOT / str(session_id)

    if session_path.is_symlink():
        raise SnapshotError("session path is a symlink; refusing snapshot access")

    if create:
        session_path.mkdir(parents=True, exist_ok=True)

    if session_path.exists() and not session_path.is_dir():
        raise SnapshotError("session path is not a directory")

    try:
        session_path.resolve(strict=False).relative_to(sessions_root)
    except ValueError as e:
        raise SnapshotError("session path escapes sessions root") from e

    return session_path


def _snapshot_dirs(session_path: Path) -> list[str]:
    """Return session-relative directories that should be archived.

    ``outputs`` is required; the others are included only when present and
    non-empty. Refuse top-level symlinks so a compromised workspace cannot
    redirect snapshotting outside the session tree.
    """
    outputs_path = session_path / "outputs"
    if session_path.is_symlink():
        raise SnapshotError("session path is a symlink; refusing to snapshot")
    if session_path.exists() and not session_path.is_dir():
        raise SnapshotError("session path is not a directory")
    if outputs_path.is_symlink():
        raise SnapshotError("outputs is a symlink; refusing to snapshot")
    if not outputs_path.is_dir():
        return []

    dirs = ["outputs"]
    candidate = session_path / "attachments"
    if candidate.is_symlink():
        raise SnapshotError("attachments is a symlink; refusing to snapshot")
    if candidate.is_dir() and any(candidate.iterdir()):
        dirs.append("attachments")
    return dirs


def _is_excluded_snapshot_dir(relative_path: Path) -> bool:
    """True for generated dependency/build directories under outputs/."""
    parts = relative_path.parts
    return (
        len(parts) >= 2
        and parts[0] == "outputs"
        and any(part in _SNAPSHOT_GENERATED_DIR_NAMES for part in parts[1:])
    )


def _add_excluded_snapshot_path(
    skipped_paths: list[tuple[str, str]],
    skipped_path_set: set[str],
    entry: Path,
    session_path: Path,
    reason: str,
) -> None:
    relative_path = entry.relative_to(session_path).as_posix()
    if relative_path in skipped_path_set:
        return
    skipped_path_set.add(relative_path)
    skipped_paths.append((relative_path, reason))


def _log_skipped_snapshot_paths(skipped_paths: list[tuple[str, str]]) -> None:
    if not skipped_paths:
        return

    sample = ", ".join(
        f"{path} ({reason})"
        for path, reason in skipped_paths[:_SKIPPED_PATH_LOG_SAMPLE_LIMIT]
    )
    remaining_count = len(skipped_paths) - _SKIPPED_PATH_LOG_SAMPLE_LIMIT
    suffix = f", ... and {remaining_count} more" if remaining_count > 0 else ""
    logger.warning(
        "Skipping %s unsupported/generated snapshot paths: %s%s",
        len(skipped_paths),
        sample,
        suffix,
    )


def _snapshot_entry_skip_reason(
    relative_path: Path,
    mode: int,
    link_count: int,
) -> str | None:
    if _is_excluded_snapshot_dir(relative_path):
        return "generated"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISREG(mode) and link_count > 1:
        return "hardlink"
    if stat.S_ISDIR(mode) or stat.S_ISREG(mode):
        return None
    return "special"


def _validate_snapshot_tree(session_path: Path, dirs: list[str]) -> list[str]:
    """Validate snapshot roots and return nested paths to exclude from tar.

    Root escape hatches still fail the snapshot. Nested unsupported filesystem
    entries are excluded instead so one symlink or FIFO does not block
    snapshotting the rest of the workspace.
    """
    session_root = session_path.resolve()
    total_uncompressed_bytes = 0
    skipped_paths: list[tuple[str, str]] = []
    skipped_path_set: set[str] = set()

    for dirname in dirs:
        root_path = session_path / dirname
        try:
            root_path.resolve(strict=False).relative_to(session_root)
        except ValueError as e:
            raise SnapshotError(f"{dirname} escapes session") from e

        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
            current = Path(dirpath)
            visible_dirnames: list[str] = []
            for dirname in dirnames:
                entry = current / dirname
                relative_dir = entry.relative_to(session_path)
                try:
                    entry_stat = entry.lstat()
                except OSError:
                    _add_excluded_snapshot_path(
                        skipped_paths,
                        skipped_path_set,
                        entry,
                        session_path,
                        "unreadable",
                    )
                    continue

                reason = _snapshot_entry_skip_reason(
                    relative_dir,
                    entry_stat.st_mode,
                    entry_stat.st_nlink,
                )
                if reason is not None:
                    _add_excluded_snapshot_path(
                        skipped_paths,
                        skipped_path_set,
                        entry,
                        session_path,
                        reason,
                    )
                    continue

                visible_dirnames.append(dirname)
            dirnames[:] = visible_dirnames

            for filename in filenames:
                entry = current / filename
                relative_file = entry.relative_to(session_path)
                try:
                    entry_stat = entry.lstat()
                except OSError:
                    _add_excluded_snapshot_path(
                        skipped_paths,
                        skipped_path_set,
                        entry,
                        session_path,
                        "unreadable",
                    )
                    continue

                reason = _snapshot_entry_skip_reason(
                    relative_file,
                    entry_stat.st_mode,
                    entry_stat.st_nlink,
                )
                if reason is not None:
                    _add_excluded_snapshot_path(
                        skipped_paths,
                        skipped_path_set,
                        entry,
                        session_path,
                        reason,
                    )
                    continue
                if stat.S_ISREG(entry_stat.st_mode):
                    total_uncompressed_bytes += entry_stat.st_size
                    if total_uncompressed_bytes > MAX_SNAPSHOT_UNCOMPRESSED_BYTES:
                        raise SnapshotError(
                            "snapshot uncompressed size exceeds "
                            f"{MAX_SNAPSHOT_UNCOMPRESSED_BYTES} byte limit"
                        )
                    continue

    _log_skipped_snapshot_paths(skipped_paths)
    return [path for path, _reason in skipped_paths]


def _validate_snapshot_member(member: tarfile.TarInfo) -> str:
    """Return a normalized member name if it is safe for session extraction."""
    try:
        member.name.encode("utf-8")
    except UnicodeEncodeError as e:
        raise SnapshotError(f"non-UTF-8 snapshot path: {member.name!r}") from e

    if os.path.isabs(member.name):
        raise SnapshotError(f"absolute snapshot path is not allowed: {member.name}")

    normalized = os.path.normpath(member.name)
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        raise SnapshotError(f"snapshot path escapes session: {member.name}")

    root = normalized.split(os.sep, 1)[0]
    if member.issym() or member.islnk():
        raise SnapshotError(f"snapshot links are not allowed: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise SnapshotError(f"snapshot special file is not allowed: {member.name}")
    if root not in _SNAPSHOT_ROOTS:
        raise SnapshotError(f"snapshot path has unexpected root: {member.name}")
    if normalized == root and not member.isdir():
        raise SnapshotError(f"snapshot root must be a directory: {member.name}")

    return normalized


def _replace_snapshot_roots(
    session_path: Path,
    staging_path: Path,
    roots: set[str],
) -> None:
    for root in sorted(roots):
        target = session_path / root
        replacement = staging_path / root
        if target.is_symlink() or target.is_file():
            target.unlink()
        elif target.exists():
            shutil.rmtree(target)
        if replacement.exists():
            os.replace(replacement, target)


def _extract_snapshot_archive(archive_path: Path, session_path: Path) -> None:
    members: list[tuple[tarfile.TarInfo, str]] = []
    roots: set[str] = set()
    total_uncompressed_bytes = 0

    try:
        with tempfile.TemporaryDirectory(
            dir=session_path,
            prefix=".snapshot-restore-",
        ) as tmp_dir:
            staging_path = Path(tmp_dir)

            with tarfile.open(archive_path, "r:gz") as tar:
                for member in tar.getmembers():
                    normalized = _validate_snapshot_member(member)
                    roots.add(normalized.split(os.sep, 1)[0])
                    if member.isfile():
                        total_uncompressed_bytes += member.size
                        if total_uncompressed_bytes > MAX_SNAPSHOT_UNCOMPRESSED_BYTES:
                            raise SnapshotError(
                                "snapshot uncompressed size exceeds "
                                f"{MAX_SNAPSHOT_UNCOMPRESSED_BYTES} byte limit"
                            )
                    members.append((member, normalized))

                for member, normalized in members:
                    final_path = staging_path / normalized
                    try:
                        final_path.resolve(strict=False).relative_to(staging_path)
                    except ValueError as e:
                        raise SnapshotError(
                            f"snapshot path escapes session: {member.name}"
                        ) from e

                    if member.isdir():
                        final_path.mkdir(parents=True, exist_ok=True)
                        os.chmod(final_path, (member.mode or 0o755) & 0o777)
                        continue

                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    src = tar.extractfile(member)
                    if src is None:
                        raise SnapshotError(
                            f"cannot read snapshot entry: {member.name}"
                        )
                    with src, final_path.open("wb") as out_file:
                        shutil.copyfileobj(src, out_file)
                    os.chmod(final_path, (member.mode or 0o644) & 0o777)

            _replace_snapshot_roots(session_path, staging_path, roots)
    except (tarfile.TarError, OSError) as e:
        raise SnapshotError(f"invalid snapshot archive: {e}") from e


def has_snapshot_content(session_id: UUID) -> bool:
    """True when a session has an outputs/ tree worth snapshotting."""
    session_path = _safe_session_path(session_id, create=False)
    return bool(_snapshot_dirs(session_path))


def iter_snapshot_archive(session_id: UUID) -> Iterator[bytes]:
    """Create a snapshot of a session's outputs/attachments.

    Yields a tar.gz byte stream. Durable persistence is handled by the
    api-server, not the sidecar.
    """
    session_path = _safe_session_path(session_id, create=False)
    dirs = _snapshot_dirs(session_path)
    if not dirs:
        return
    exclude_paths = _validate_snapshot_tree(session_path, dirs)
    exclude_args = [f"--exclude={path}" for path in exclude_paths]

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

        proc = subprocess.run(
            [
                "tar",
                *exclude_args,
                "-czf",
                str(tmp_path),
                *dirs,
            ],
            cwd=session_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            detail = proc.stdout.strip() or "no output"
            raise SnapshotError(f"tar exited {proc.returncode}: {detail}")

        size_bytes = tmp_path.stat().st_size
        if size_bytes > MAX_SNAPSHOT_ARCHIVE_BYTES:
            raise SnapshotError(
                f"snapshot archive exceeds {MAX_SNAPSHOT_ARCHIVE_BYTES} byte limit"
            )

        with tmp_path.open("rb") as archive_file:
            while True:
                chunk = archive_file.read(_ARCHIVE_CHUNK_BYTES)
                if not chunk:
                    break
                yield chunk
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def restore_snapshot(
    session_id: UUID,
    archive_path: Path,
) -> None:
    """Extract a local snapshot archive, then bun-install to rebuild node_modules."""
    session_path = _safe_session_path(session_id, create=True)

    # Keep in sync with docker_sandbox_manager.restore_snapshot's install.
    script = """
set -eo pipefail

web_dir="$SESSION_PATH/outputs/web"
if [ -f "$web_dir/bun.lock" ]; then
    (
        flock -x 9
        if [ ! -f "$BUN_CACHE_DIR/.ready" ]; then
            rm -rf "$BUN_CACHE_DIR"
            cp -r "$BUN_IMAGE_CACHE_DIR" "$BUN_CACHE_DIR" \\
                || { echo "ERROR: bun cache bootstrap failed" >&2; exit 1; }
            touch "$BUN_CACHE_DIR/.ready"
        fi
    ) 9>"$BUN_CACHE_DIR.lock"
    cd "$web_dir"
    BUN_INSTALL_CACHE_DIR="$BUN_CACHE_DIR" \\
        bun install --frozen-lockfile --backend=hardlink
fi
"""

    try:
        _extract_snapshot_archive(archive_path, session_path)
        subprocess.run(
            ["/bin/bash", "-c", script],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={
                **os.environ,
                "ARCHIVE_PATH": str(archive_path),
                "SESSION_PATH": str(session_path),
                "BUN_CACHE_DIR": str(BUN_CACHE_DIR),
                "BUN_IMAGE_CACHE_DIR": str(BUN_IMAGE_CACHE_DIR),
            },
        )
    except subprocess.CalledProcessError as e:
        detail = (e.stdout or "").strip() or "no output"
        raise SnapshotError(f"exit {e.returncode}: {detail}") from e
