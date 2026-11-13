import os
import shutil
import tarfile
import threading
from datetime import UTC, datetime
from pathlib import Path

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MiB per entry
# The run-time skill limit (onyx/skills/limits.py) imports this cap.
MAX_BUNDLE_BYTES = 900 * 1024 * 1024  # 900 MiB total uncompressed
# The body is tar.gz: tar headers, block padding and gzip framing can make an
# archive of incompressible files larger than its content.
MAX_ARCHIVE_BYTES = MAX_BUNDLE_BYTES + 64 * 1024 * 1024
ALLOWED_PREFIX = "/workspace/managed/"
OLD_DIR_GRACE_SECONDS = 60
_COPY_CHUNK_BYTES = 1024 * 1024


def _validate_member(member: tarfile.TarInfo, bundle_root: str) -> None:
    try:
        member.name.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"Non-UTF-8 path name: {member.name!r}")

    if member.issym() or member.islnk():
        raise ValueError(f"Links not allowed: {member.name}")

    if not (member.isreg() or member.isdir()):
        raise ValueError(f"Special file not allowed: {member.name}")

    resolved = os.path.normpath(os.path.join(bundle_root, member.name))
    if not resolved.startswith(
        os.path.normpath(bundle_root) + os.sep
    ) and resolved != os.path.normpath(bundle_root):
        raise ValueError(f"Path traversal detected: {member.name}")

    if os.path.isabs(member.name):
        raise ValueError(f"Absolute path not allowed: {member.name}")

    if member.isreg() and member.size > MAX_FILE_BYTES:
        raise ValueError(
            f"Entry too large: {member.name} ({member.size} > {MAX_FILE_BYTES})"
        )


def _schedule_removal(path: str) -> None:
    def _remove() -> None:
        shutil.rmtree(path, ignore_errors=True)

    timer = threading.Timer(OLD_DIR_GRACE_SECONDS, _remove)
    timer.daemon = True
    timer.start()


def _live_target(mount: Path) -> str | None:
    if not mount.is_symlink():
        return None
    target = os.readlink(mount)
    if not os.path.isabs(target):
        target = str((mount.parent / target).resolve())
    return target


def _remove_stale_versions(versions_dir: Path, live: str | None) -> None:
    """Remove this mount's versions except the live one, so the mount never
    holds more than the live tree and the incoming tree."""
    if not versions_dir.is_dir():
        return
    for entry in versions_dir.iterdir():
        if str(entry) != live:
            shutil.rmtree(entry, ignore_errors=True)


def _extract(archive_path: Path, dest: Path) -> None:
    total_size = 0
    with tarfile.open(archive_path, mode="r:gz") as tar:
        for member in tar:
            _validate_member(member, str(dest))

            if member.isreg():
                total_size += member.size
                if total_size > MAX_BUNDLE_BYTES:
                    raise ValueError(
                        f"Total uncompressed size exceeds {MAX_BUNDLE_BYTES}"
                    )

            final_path = Path(os.path.normpath(os.path.join(str(dest), member.name)))
            if not str(final_path).startswith(ALLOWED_PREFIX):
                raise ValueError(f"Extracted path escapes allow-list: {final_path}")

            if member.isdir():
                os.makedirs(final_path, exist_ok=True)
            elif member.isreg():
                os.makedirs(str(final_path.parent), exist_ok=True)
                src = tar.extractfile(member)
                if src is None:
                    raise ValueError(f"Cannot read entry: {member.name}")
                with src, open(final_path, "wb") as f:
                    shutil.copyfileobj(src, f, _COPY_CHUNK_BYTES)
                # 0o755 mask strips setuid (4000), setgid (2000), sticky (1000), and group/other write (022)
                os.chmod(final_path, (member.mode or 0o644) & 0o755)


def safe_extract_then_atomic_swap(archive_path: Path, mount_path: str) -> None:
    """Extract a tar.gz file into a new version and point the mount at it.

    The caller runs one push at a time. On any failure the mount is unchanged.
    """
    mount = Path(mount_path)
    versions_dir = mount.parent / ".versions" / mount.name
    sha_prefix = os.urandom(4).hex()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = versions_dir / f"{timestamp}-{sha_prefix}"

    if not str(dest.resolve()).startswith(ALLOWED_PREFIX):
        raise ValueError(
            f"mount_path resolves outside {ALLOWED_PREFIX}: {dest.resolve()}"
        )

    old_target = _live_target(mount)
    _remove_stale_versions(versions_dir, old_target)
    os.makedirs(dest)

    try:
        _extract(archive_path, dest)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    tmp_link = f"{mount}.tmp.{os.getpid()}.{os.urandom(4).hex()}"
    os.symlink(str(dest), tmp_link)
    try:
        os.rename(tmp_link, str(mount))
    except OSError:
        os.unlink(tmp_link)
        shutil.rmtree(dest, ignore_errors=True)
        raise

    if old_target and os.path.isdir(old_target):
        _schedule_removal(old_target)
