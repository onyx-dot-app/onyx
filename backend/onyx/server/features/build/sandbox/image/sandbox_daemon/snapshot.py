"""Snapshot create/restore operations for the sandbox sidecar.

The sidecar owns pod-local filesystem access. The api-server owns durable
storage by streaming these tarballs into/out of the main Onyx FileStore.
"""

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


class SnapshotError(RuntimeError):
    """Raised when tar or bun fails so the manager can see the cause."""


_SNAPSHOT_ROOTS = frozenset({"outputs", "attachments", ".opencode-data"})
_SNAPSHOT_GENERATED_DIR_NAMES = frozenset({"node_modules", ".next"})
MAX_SNAPSHOT_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_SNAPSHOT_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
_ARCHIVE_CHUNK_BYTES = 1024 * 1024


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
    for subdir in ("attachments", ".opencode-data"):
        candidate = session_path / subdir
        if candidate.is_symlink():
            raise SnapshotError(f"{subdir} is a symlink; refusing to snapshot")
        if candidate.is_dir() and any(candidate.iterdir()):
            dirs.append(subdir)
    return dirs


def _is_excluded_snapshot_dir(relative_path: Path) -> bool:
    """True for generated dependency/build directories under outputs/."""
    parts = relative_path.parts
    return (
        len(parts) >= 2
        and parts[0] == "outputs"
        and any(part in _SNAPSHOT_GENERATED_DIR_NAMES for part in parts[1:])
    )


def _snapshot_tar_exclude_paths(session_path: Path) -> list[str]:
    """Return session-relative generated directories to exclude from tar."""
    outputs_path = session_path / "outputs"
    if not outputs_path.is_dir():
        return []

    excluded_paths: list[str] = []
    for dirpath, dirnames, _filenames in os.walk(outputs_path, followlinks=False):
        current = Path(dirpath)
        visible_dirnames: list[str] = []
        for dirname in dirnames:
            relative_dir = (current / dirname).relative_to(session_path)
            if _is_excluded_snapshot_dir(relative_dir):
                excluded_paths.append(relative_dir.as_posix())
                continue
            visible_dirnames.append(dirname)
        dirnames[:] = visible_dirnames
    return excluded_paths


def _validate_snapshot_tree(session_path: Path, dirs: list[str]) -> None:
    """Refuse filesystem entries that restore will reject or that can escape."""
    session_root = session_path.resolve()
    total_uncompressed_bytes = 0
    for dirname in dirs:
        root_path = session_path / dirname
        try:
            root_path.resolve(strict=False).relative_to(session_root)
        except ValueError as e:
            raise SnapshotError(f"{dirname} escapes session") from e

        for dirpath, dirnames, filenames in os.walk(root_path, followlinks=False):
            current = Path(dirpath)
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if not _is_excluded_snapshot_dir(
                    (current / dirname).relative_to(session_path)
                )
            ]
            entries = [current, *(current / name for name in dirnames)]
            entries.extend(current / name for name in filenames)
            for entry in entries:
                try:
                    mode = entry.lstat().st_mode
                except OSError as e:
                    raise SnapshotError(f"cannot stat snapshot entry: {entry}") from e

                if stat.S_ISLNK(mode):
                    rel = entry.relative_to(session_path)
                    raise SnapshotError(f"snapshot links are not allowed: {rel}")
                if stat.S_ISDIR(mode):
                    continue
                if stat.S_ISREG(mode):
                    total_uncompressed_bytes += entry.lstat().st_size
                    if total_uncompressed_bytes > MAX_SNAPSHOT_UNCOMPRESSED_BYTES:
                        raise SnapshotError(
                            "snapshot uncompressed size exceeds "
                            f"{MAX_SNAPSHOT_UNCOMPRESSED_BYTES} byte limit"
                        )
                    continue

                rel = entry.relative_to(session_path)
                raise SnapshotError(f"snapshot special file is not allowed: {rel}")


def _validate_snapshot_member(member: tarfile.TarInfo) -> str:
    """Return a normalized member name if it is safe for session extraction."""
    try:
        member.name.encode("utf-8")
    except UnicodeEncodeError as e:
        raise SnapshotError(f"non-UTF-8 snapshot path: {member.name!r}") from e

    if member.issym() or member.islnk():
        raise SnapshotError(f"snapshot links are not allowed: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise SnapshotError(f"snapshot special file is not allowed: {member.name}")
    if os.path.isabs(member.name):
        raise SnapshotError(f"absolute snapshot path is not allowed: {member.name}")

    normalized = os.path.normpath(member.name)
    if normalized in ("", ".") or normalized == ".." or normalized.startswith("../"):
        raise SnapshotError(f"snapshot path escapes session: {member.name}")

    root = normalized.split(os.sep, 1)[0]
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
    """Create a snapshot of a session's outputs/attachments/.opencode-data.

    Yields a tar.gz byte stream. Durable persistence is handled by the
    api-server, not the sidecar.
    """
    session_path = _safe_session_path(session_id, create=False)
    dirs = _snapshot_dirs(session_path)
    if not dirs:
        return
    _validate_snapshot_tree(session_path, dirs)
    exclude_args = [
        f"--exclude={path}" for path in _snapshot_tar_exclude_paths(session_path)
    ]

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
