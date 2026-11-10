import gzip
import os
import shutil
import tarfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, cast

from sandbox_daemon.models import (
    PUSH_MAX_CONTENT_BYTES,
    PUSH_MAX_DIRECTORIES,
    PUSH_MAX_FILE_BYTES,
    PUSH_MAX_FILES,
    PUSH_MAX_TAR_BYTES,
    push_path_byte_limit,
    push_version_directory,
    validate_push_path,
)

MAX_FILE_BYTES = PUSH_MAX_FILE_BYTES
ALLOWED_PREFIX = "/workspace/managed/"
OLD_DIR_GRACE_SECONDS = 60
# Entry data is copied in chunks of this size.
_COPY_CHUNK_BYTES = 1024 * 1024
# tarfile keeps each header, including PAX and GNU long-name data, in memory.
_MAX_HEADER_BYTES = 1024 * 1024

# One extraction at a time bounds disk use and keeps the version sweep safe.
_extract_lock = threading.Lock()


class _BoundedTarStream:
    """Decompressed tar stream that bounds header reads and the stream size.

    Reads inside the data of the current member are not counted. Every other
    read is header data, and the headers of one member share one budget.
    """

    def __init__(self, fileobj: gzip.GzipFile) -> None:
        self._fileobj = fileobj
        self._data_start = 0
        self._data_end = 0
        self._header_bytes = 0

    def start_member(self, member: tarfile.TarInfo) -> None:
        self._data_start = member.offset_data
        self._data_end = member.offset_data + member.size
        self._header_bytes = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise ValueError("Unbounded tar read")
        position = self._fileobj.tell()
        if not (self._data_start <= position and position + size <= self._data_end):
            self._header_bytes += size
            if self._header_bytes > _MAX_HEADER_BYTES:
                raise ValueError("Tar metadata entry too large")
        data = self._fileobj.read(size)
        self._check_position(self._fileobj.tell())
        return data

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence != os.SEEK_SET:
            raise ValueError("Unsupported tar seek")
        self._check_position(offset)
        return self._fileobj.seek(offset)

    def tell(self) -> int:
        return self._fileobj.tell()

    @staticmethod
    def _check_position(position: int) -> None:
        if position > PUSH_MAX_TAR_BYTES:
            raise ValueError(f"Tar stream exceeds {PUSH_MAX_TAR_BYTES} bytes")


def _validate_member(member: tarfile.TarInfo, bundle_root: str) -> None:
    validate_push_path(member.name, push_path_byte_limit(bundle_root))

    if member.issym() or member.islnk():
        raise ValueError(f"Links not allowed: {member.name}")

    if member.issparse() or not (member.isreg() or member.isdir()):
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


def _current_target(mount: Path) -> str | None:
    if not mount.is_symlink():
        return None
    target = os.readlink(mount)
    if not os.path.isabs(target):
        target = str((mount.parent / target).resolve())
    return target


def _remove_stale_versions(versions_dir: Path, keep: str | None) -> None:
    """Remove this mount's versions except the live one.

    This ends the grace period of the previous version early and removes trees
    left by an interrupted sidecar, so a mount never holds more than its live
    tree and one incoming tree.
    """
    if not versions_dir.is_dir():
        return
    for entry in versions_dir.iterdir():
        if keep is None or str(entry) != keep:
            shutil.rmtree(entry, ignore_errors=True)


def _extract_archive(archive_path: Path, dest: Path) -> None:
    content_bytes = 0
    file_count = 0
    directories: set[str] = set()

    def _count_directory(relative_dir: str) -> None:
        if relative_dir in directories:
            return
        directories.add(relative_dir)
        if len(directories) > PUSH_MAX_DIRECTORIES:
            raise ValueError(f"Bundle has more than {PUSH_MAX_DIRECTORIES} folders")

    with gzip.GzipFile(filename=archive_path, mode="rb") as gzip_file:
        stream = _BoundedTarStream(gzip_file)
        # tarfile only reads, seeks and tells on a caller-owned stream.
        with tarfile.open(fileobj=cast(IO[bytes], stream), mode="r:") as tar:
            for member in tar:
                _validate_member(member, str(dest))
                stream.start_member(member)

                final_path = Path(os.path.normpath(os.path.join(dest, member.name)))
                if not str(final_path).startswith(ALLOWED_PREFIX):
                    raise ValueError(f"Extracted path escapes allow-list: {final_path}")

                parts = final_path.relative_to(dest).parts
                dir_depth = len(parts) if member.isdir() else len(parts) - 1
                for depth in range(1, dir_depth + 1):
                    _count_directory("/".join(parts[:depth]))

                if member.isdir():
                    os.makedirs(final_path, exist_ok=True)
                    continue

                file_count += 1
                if file_count > PUSH_MAX_FILES:
                    raise ValueError(f"Bundle has more than {PUSH_MAX_FILES} files")
                content_bytes += member.size
                if content_bytes > PUSH_MAX_CONTENT_BYTES:
                    raise ValueError(
                        f"Total uncompressed size exceeds {PUSH_MAX_CONTENT_BYTES}"
                    )

                os.makedirs(final_path.parent, exist_ok=True)
                src = tar.extractfile(member)
                if src is None:
                    raise ValueError(f"Cannot read entry: {member.name}")
                with src, open(final_path, "wb") as f:
                    shutil.copyfileobj(src, f, _COPY_CHUNK_BYTES)
                # 0o755 mask strips setuid (4000), setgid (2000), sticky (1000), and group/other write (022)
                os.chmod(final_path, (member.mode or 0o644) & 0o755)


def safe_extract_then_atomic_swap(archive_path: Path, mount_path: str) -> None:
    """Extract a verified tar.gz file into a new version and point the mount at it.

    The previous version stays readable for OLD_DIR_GRACE_SECONDS or until the
    next push to the same mount. On any failure, the mount is not changed.
    """
    mount = Path(mount_path)
    sha_prefix = os.urandom(4).hex()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    version_name = f"{timestamp}-{sha_prefix}"
    dest = Path(push_version_directory(mount_path, version_name))
    versions_dir = dest.parent

    if not str(dest.resolve()).startswith(ALLOWED_PREFIX):
        raise ValueError(
            f"mount_path resolves outside {ALLOWED_PREFIX}: {dest.resolve()}"
        )

    with _extract_lock:
        old_target = _current_target(mount)
        _remove_stale_versions(versions_dir, keep=old_target)
        os.makedirs(dest)

        try:
            _extract_archive(archive_path, dest)
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
