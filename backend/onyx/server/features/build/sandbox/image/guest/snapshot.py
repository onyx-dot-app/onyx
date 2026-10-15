"""Session snapshot archives, with durable storage owned by the API server."""

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
# Must match onyx.server.features.build.configs.BUN_CACHE_DIR -- the
# guest cannot import from the API server package at runtime.
BUN_CACHE_DIR = SESSIONS_ROOT / ".bun-cache"
BUN_IMAGE_CACHE_DIR = Path("/home/sandbox/.bun/install/cache")
logger = logging.getLogger(__name__)


class SnapshotError(RuntimeError):
    """Raised when tar or bun fails so the manager can see the cause."""


_SNAPSHOT_ROOTS = frozenset({"outputs", "attachments"})
_SNAPSHOT_GENERATED_DIR_NAMES = frozenset({"node_modules", ".next"})
# Excluded so a restore can't reintroduce a stale port/pid that would mislead
# the webapp tool's liveness check when auto-start is skipped.
_SNAPSHOT_GENERATED_FILE_NAMES = frozenset({".nextjs-port", "nextjs.pid"})
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
    """True for generated dependency/build directories, or excluded runtime
    scratch files, under outputs/."""
    parts = relative_path.parts
    if len(parts) < 2 or parts[0] != "outputs":
        return False
    if parts[1] == ".document-thumbnails":
        return True
    if any(part in _SNAPSHOT_GENERATED_DIR_NAMES for part in parts[1:]):
        return True
    return relative_path.name in _SNAPSHOT_GENERATED_FILE_NAMES


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
) -> str | None:
    if _is_excluded_snapshot_dir(relative_path):
        return "generated"
    if stat.S_ISLNK(mode):
        return "symlink"
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


def _normalize_snapshot_path(name: str) -> str:
    """Validate archive-relative member names and hardlink targets."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError as e:
        raise SnapshotError(f"non-UTF-8 snapshot path: {name!r}") from e

    if "\x00" in name:
        raise SnapshotError(f"invalid snapshot path: {name!r}")
    if os.path.isabs(name):
        raise SnapshotError(f"absolute snapshot path is not allowed: {name}")

    normalized = os.path.normpath(name)
    if normalized in ("", ".") or ".." in Path(name).parts:
        raise SnapshotError(f"snapshot path escapes session: {name}")

    root = normalized.split(os.sep, 1)[0]
    if root not in _SNAPSHOT_ROOTS:
        raise SnapshotError(f"snapshot path has unexpected root: {name}")
    return normalized


def _validate_snapshot_member(member: tarfile.TarInfo, normalized: str) -> None:
    """Validate type and size after archive path normalization."""
    if member.issym():
        raise SnapshotError(f"snapshot links are not allowed: {member.name}")
    if not (member.isfile() or member.isdir() or member.islnk()):
        raise SnapshotError(f"snapshot special file is not allowed: {member.name}")
    if member.size < 0 or (not member.isfile() and member.size != 0):
        raise SnapshotError(f"invalid snapshot entry size: {member.name}")
    root = normalized.split(os.sep, 1)[0]
    if normalized == root and not member.isdir():
        raise SnapshotError(f"snapshot root must be a directory: {member.name}")


def _remove_workspace_tree(path: Path) -> None:
    """Retry owned-tree removal once after repairing directory permissions."""
    try:
        shutil.rmtree(path)
    except PermissionError:
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise SnapshotError("workspace cleanup path is not a directory")

        def allow_owner_access(directory: Path) -> None:
            metadata = directory.lstat()
            if stat.S_ISDIR(metadata.st_mode):
                os.chmod(
                    directory,
                    stat.S_IMODE(metadata.st_mode) | stat.S_IRWXU,
                    follow_symlinks=False,
                )

        def raise_walk_error(error: OSError) -> None:
            raise error

        allow_owner_access(path)
        for dirpath, dirnames, _ in os.walk(
            path, followlinks=False, onerror=raise_walk_error
        ):
            for name in dirnames:
                allow_owner_access(Path(dirpath) / name)
        shutil.rmtree(path)


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
            _remove_workspace_tree(target)
        if replacement.exists():
            os.replace(replacement, target)


def _extract_snapshot_archive(archive_path: Path, session_path: Path) -> None:
    file_members: list[tuple[tarfile.TarInfo, str, tarfile.TarInfo]] = []
    directory_modes: dict[str, int] = {}
    prior_regular_members: dict[str, tarfile.TarInfo] = {}
    member_names: set[str] = set()
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
                    normalized = _normalize_snapshot_path(member.name)
                    if normalized in member_names:
                        raise SnapshotError(f"duplicate snapshot path: {member.name}")
                    member_names.add(normalized)
                    excluded = _is_excluded_snapshot_dir(Path(normalized))
                    if not excluded or member.isfile():
                        _validate_snapshot_member(member, normalized)
                    if member.isfile():
                        prior_regular_members[normalized] = member
                    if excluded:
                        continue
                    roots.add(normalized.split(os.sep, 1)[0])
                    if member.isdir():
                        directory_modes[normalized] = (member.mode or 0o755) & 0o777
                        continue

                    source = member
                    if member.islnk():
                        try:
                            target = _normalize_snapshot_path(member.linkname)
                        except SnapshotError as error:
                            raise SnapshotError(
                                f"invalid snapshot hardlink target: {member.linkname}: {error}"
                            ) from error
                        if target not in prior_regular_members:
                            raise SnapshotError(
                                "snapshot hardlink target is not a preceding regular "
                                f"file: {member.name} -> {member.linkname}"
                            )
                        source = prior_regular_members[target]
                    total_uncompressed_bytes += source.size
                    if total_uncompressed_bytes > MAX_SNAPSHOT_UNCOMPRESSED_BYTES:
                        raise SnapshotError(
                            "snapshot uncompressed size exceeds "
                            f"{MAX_SNAPSHOT_UNCOMPRESSED_BYTES} byte limit"
                        )
                    file_members.append((member, normalized, source))

                for normalized in directory_modes:
                    (staging_path / normalized).mkdir(parents=True, exist_ok=True)

                for member, normalized, source in file_members:
                    final_path = staging_path / normalized
                    try:
                        final_path.resolve(strict=False).relative_to(staging_path)
                    except ValueError as e:
                        raise SnapshotError(
                            f"snapshot path escapes session: {member.name}"
                        ) from e

                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    src = tar.extractfile(source)
                    if src is None:
                        raise SnapshotError(
                            f"cannot read snapshot entry: {member.name}"
                        )
                    with src, final_path.open("wb") as out_file:
                        shutil.copyfileobj(src, out_file)
                    os.chmod(final_path, (member.mode or 0o644) & 0o777)

            for normalized in sorted(
                directory_modes, key=lambda name: name.count(os.sep), reverse=True
            ):
                if normalized not in roots:
                    os.chmod(staging_path / normalized, directory_modes[normalized])

            _replace_snapshot_roots(session_path, staging_path, roots)
            # Linux cross-parent renames need write access to the moved directory.
            for root in roots:
                if root in directory_modes:
                    os.chmod(session_path / root, directory_modes[root])
    except (tarfile.TarError, OSError) as e:
        raise SnapshotError(f"invalid snapshot archive: {e}") from e


def has_snapshot_content(session_id: UUID) -> bool:
    """True when a session has an outputs/ tree worth snapshotting."""
    session_path = _safe_session_path(session_id, create=False)
    return bool(_snapshot_dirs(session_path))


def iter_snapshot_archive(session_id: UUID) -> Iterator[bytes]:
    """Create a snapshot of a session's outputs/attachments.

    Yields a tar.gz byte stream. Durable persistence is handled by the
    API server.
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
                "--hard-dereference",
                *exclude_args,
                "-czf",
                str(tmp_path),
                *dirs,
            ],
            cwd=session_path,
            stdin=subprocess.DEVNULL,
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
        bun install --frozen-lockfile --ignore-scripts --backend=hardlink
fi
"""

    try:
        _extract_snapshot_archive(archive_path, session_path)
        subprocess.run(
            ["/bin/bash", "-c", script],
            check=True,
            stdin=subprocess.DEVNULL,
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
