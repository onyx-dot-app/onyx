"""Bounded access to repository archives without extracting paths."""

import gzip
import io
import stat
import struct
import sys
import tarfile
import zipfile
from collections.abc import Buffer, Callable, Iterator
from contextlib import ExitStack, contextmanager
from functools import partial
from tarfile import HeaderError, ReadError, TarFile
from tempfile import SpooledTemporaryFile
from typing import Self, cast

ARCHIVE_MAX_BYTES = 25 * 1024 * 1024
ARCHIVE_MAX_ENTRIES = 10_000
ARCHIVE_PATH_MAX_BYTES = 4096
ARCHIVE_PATH_MAX_DEPTH = 64
ARCHIVE_INDEX_MAX_BYTES = 25 * 1024 * 1024
ZIP_METADATA_MAX_BYTES = 1024 * 1024
TAR_METADATA_MAX_BYTES = 16 * 1024 * 1024
# Bounds header chains, parser recursion and parsed metadata per TAR member.
TAR_MEMBER_METADATA_MAX_BYTES = 32 * 1024
MANIFEST_MAX_BYTES = 1024 * 1024
# Independent processing ceilings, not per-skill validation limits.
EXPANDED_MAX_BYTES = 1024 * 1024 * 1024
MEMBER_READ_MAX_BYTES = 1024 * 1024 * 1024
MEMBER_CALL_MAX_BYTES = 4 * 1024 * 1024
SPOOL_MEMORY_BYTES = 1024 * 1024

type ArchiveFiles = dict[str, Callable[[], io.BufferedIOBase] | None]


class ArchiveLimitError(ValueError):
    """The whole read failed; callers must not infer removed entries."""


def archive_path(value: str) -> str:
    if value in ("", ".", "./"):
        return ""
    if (
        len(value) > ARCHIVE_PATH_MAX_BYTES
        or len(value.encode()) > ARCHIVE_PATH_MAX_BYTES
    ):
        raise ArchiveLimitError("Archive path is too long")
    value = value.removeprefix("./")
    if len(value) >= 3 and value[0].isalpha() and value[1:3] == ":/":
        raise ValueError(f"Unsafe path: {value!r}")
    value = value.removesuffix("/")
    if value.count("/") >= ARCHIVE_PATH_MAX_DEPTH:
        raise ArchiveLimitError("Archive path is too deep")
    if any(c in value for c in ("\\", "\x00")) or any(
        part in ("", ".", "..") for part in value.split("/")
    ):
        raise ValueError(f"Unsafe path: {value!r}")
    return value


def require_regular_path(files: ArchiveFiles, path: str) -> None:
    parts = path.split("/")
    for index in range(1, len(parts) + 1):
        prefix = "/".join(parts[:index])
        if prefix in files and files[prefix] is None:
            raise ValueError(f"Unreadable archive member: {prefix}")


class _ReadBudget:
    def __init__(self) -> None:
        self.remaining = MEMBER_READ_MAX_BYTES

    def consume(self, size: int) -> None:
        self.remaining -= size
        if self.remaining < 0:
            raise ArchiveLimitError(
                f"Archive member reads exceed {MEMBER_READ_MAX_BYTES} bytes"
            )


class _MemberReader(io.BufferedIOBase):
    def __init__(
        self, source: io.BufferedIOBase, budget: _ReadBudget, *, allow_seek: bool
    ) -> None:
        super().__init__()
        self.source = source
        self.budget = budget
        self.allow_seek = allow_seek

    def read(self, size: int | None = -1, /) -> bytes:
        # One call never returns more than MEMBER_CALL_MAX_BYTES or truncates.
        if size is None or size < 0 or size > MEMBER_CALL_MAX_BYTES:
            size = MEMBER_CALL_MAX_BYTES + 1
        data = self.source.read(min(size, self.budget.remaining + 1))
        self.budget.consume(len(data))
        if len(data) > MEMBER_CALL_MAX_BYTES:
            raise ArchiveLimitError(
                f"Archive member read exceeds {MEMBER_CALL_MAX_BYTES} bytes per call"
            )
        return data

    def read1(self, size: int = -1, /) -> bytes:
        # Short read1 results are valid, unlike short read results.
        return self.read(
            min(size, MEMBER_CALL_MAX_BYTES) if size >= 0 else MEMBER_CALL_MAX_BYTES
        )

    def readinto(self, buffer: Buffer, /) -> int:
        with memoryview(buffer).cast("B") as view:
            filled = 0
            while filled < view.nbytes and (data := self.read1(view.nbytes - filled)):
                view[filled : filled + len(data)] = data
                filled += len(data)
            return filled

    def readline(self, size: int | None = -1, /) -> bytes:
        if size is None or size < 0 or size > MEMBER_CALL_MAX_BYTES:
            size = MEMBER_CALL_MAX_BYTES + 1
        line = self.source.readline(min(size, self.budget.remaining + 1))
        self.budget.consume(len(line))
        if len(line) > MEMBER_CALL_MAX_BYTES:
            raise ArchiveLimitError(
                f"Archive member read exceeds {MEMBER_CALL_MAX_BYTES} bytes per call"
            )
        return line

    def readlines(self, hint: int | None = -1, /) -> list[bytes]:
        lines: list[bytes] = []
        size = 0
        while line := self.readline(MEMBER_CALL_MAX_BYTES - size + 1):
            size += len(line)
            if size > MEMBER_CALL_MAX_BYTES:
                raise ArchiveLimitError("Archive member lines exceed the call limit")
            lines.append(line)
            if hint is not None and 0 < hint <= size:
                break
        return lines

    def readable(self) -> bool:
        return self.source.readable()

    def seekable(self) -> bool:
        return self.allow_seek and self.source.seekable()

    def seek(self, offset: int, whence: int = io.SEEK_SET, /) -> int:
        if not self.seekable():
            raise io.UnsupportedOperation("Archive ZIP members do not support seeking")
        return self.source.seek(offset, whence)

    def tell(self) -> int:
        return self.source.tell()

    def close(self) -> None:
        try:
            self.source.close()
        finally:
            super().close()


class _ZipReader(io.BytesIO):
    metadata_reads = True

    def read(self, size: int | None = -1, /) -> bytes:
        if self.metadata_reads:
            with self.getbuffer() as view:
                requested = (
                    view.nbytes - self.tell() if size is None or size < 0 else size
                )
            if requested > ZIP_METADATA_MAX_BYTES:
                raise ArchiveLimitError("Archive ZIP metadata is too large")
        return super().read(size)


class _TarReader(io.BufferedReader):
    metadata_reads = True
    last_read_was_end = False
    metadata_bytes = 0
    member_metadata_bytes = 0

    def read(self, size: int | None = -1, /) -> bytes:
        if not self.metadata_reads:
            return super().read(size)
        remaining = min(
            TAR_METADATA_MAX_BYTES - self.metadata_bytes,
            TAR_MEMBER_METADATA_MAX_BYTES - self.member_metadata_bytes,
        )
        requested = (
            remaining + 1 if size is None or size < 0 else min(size, remaining + 1)
        )
        data = super().read(requested)
        self.last_read_was_end = not data or data == bytes(512)
        self.metadata_bytes += len(data)
        self.member_metadata_bytes += len(data)
        if self.metadata_bytes > TAR_METADATA_MAX_BYTES:
            raise ArchiveLimitError("Archive TAR metadata is too large")
        if self.member_metadata_bytes > TAR_MEMBER_METADATA_MAX_BYTES:
            raise ArchiveLimitError("Archive TAR member metadata is too large")
        return data


class _StrictTarInfo(tarfile.TarInfo):
    @classmethod
    def fromtarfile(cls, tarfile: TarFile) -> Self:
        start = tarfile.fileobj.tell()
        try:
            return super().fromtarfile(tarfile)
        except HeaderError as exc:
            # Preserve normal EOF; TarFile otherwise hides corrupt later headers.
            if (
                isinstance(tarfile.fileobj, _TarReader)
                and tarfile.fileobj.last_read_was_end
                and tarfile.fileobj.tell() - start <= 512
            ):
                raise
            raise ReadError(str(exc)) from exc
        except IndexError as exc:
            # Truncated GNU sparse extensions can escape tarfile as IndexError.
            raise ReadError("Truncated TAR extension") from exc


def _open_member(
    archive: zipfile.ZipFile | tarfile.TarFile,
    member: zipfile.ZipInfo | tarfile.TarInfo,
    budget: _ReadBudget,
) -> io.BufferedIOBase:
    if isinstance(archive, zipfile.ZipFile) and isinstance(member, zipfile.ZipInfo):
        source = archive.open(member)
    elif isinstance(archive, tarfile.TarFile) and isinstance(member, tarfile.TarInfo):
        source = archive.extractfile(member)
        if source is None:
            raise ValueError(f"Unreadable archive member: {member.name}")
    else:
        raise TypeError("Archive member format mismatch")
    return _MemberReader(
        cast(io.BufferedIOBase, source),
        budget,
        allow_seek=isinstance(archive, tarfile.TarFile),
    )


def _zip_catalog_count(data: bytes) -> int:
    # Match zipfile's end-record selection, including its no-comment fast path.
    end = len(data) - 22
    if data[end : end + 4] != b"PK\x05\x06" or data[-2:] != b"\0\0":
        end = data.rfind(b"PK\x05\x06", max(0, len(data) - 65535 - 22))
    if end < 0 or end + 22 > len(data):
        raise ValueError("ZIP end record is missing")
    disk, start_disk, disk_count, count = struct.unpack_from("<4H", data, end + 4)
    locator = end - 20
    if locator >= 0 and data[locator : locator + 4] == b"PK\x06\x07":
        record = int.from_bytes(data[locator + 8 : locator + 16], "little")
        if data[record : record + 4] != b"PK\x06\x06":
            record = locator - 56  # ZIP64 with prepended executable data.
        if (
            record < 0
            or record + 56 > locator
            or data[record : record + 4] != b"PK\x06\x06"
        ):
            raise ValueError("ZIP64 end record is missing")
        length = int.from_bytes(data[record + 4 : record + 12], "little")
        if record + 12 + length != locator:
            raise ValueError("ZIP64 end record is truncated")
        disk, start_disk, disk_count, count = struct.unpack_from(
            "<IIQQ", data, record + 16
        )
    if disk or start_disk or disk_count != count:
        raise ValueError("ZIP catalog spans multiple disks")
    return count


def _require_complete_catalog(
    archive: zipfile.ZipFile | tarfile.TarFile, data: bytes, *, required: bool
) -> None:
    if not required:
        return
    if isinstance(archive, zipfile.ZipFile):
        if len(archive.infolist()) != _zip_catalog_count(data):
            raise ValueError("ZIP directory entry count does not match its end record")
        for member in archive.infolist():
            # Opening checks every local header and name without inflating content.
            with archive.open(member):
                pass
    else:
        archive.fileobj.seek(archive.offset)
        if archive.fileobj.read(2 * tarfile.BLOCKSIZE) != b"\0" * (
            2 * tarfile.BLOCKSIZE
        ):
            raise ValueError("Tar archive has no valid end marker")
        while trailing := archive.fileobj.read(64 * 1024):
            if trailing.strip(b"\0"):
                raise ValueError("Tar archive has content after its end marker")


@contextmanager
def archive_files(
    data: bytes, *, require_complete: bool = False
) -> Iterator[ArchiveFiles]:
    if len(data) > ARCHIVE_MAX_BYTES:
        raise ArchiveLimitError(f"Archive exceeds {ARCHIVE_MAX_BYTES} bytes")
    with ExitStack() as stack:
        source = stack.enter_context(_ZipReader(data))
        archive: zipfile.ZipFile | tarfile.TarFile
        buffered: _TarReader | None = None
        if zipfile.is_zipfile(source):
            archive = stack.enter_context(zipfile.ZipFile(source))
            source.metadata_reads = False
        else:
            source.metadata_reads = False
            source.seek(0)
            expanded = stack.enter_context(
                SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES)
            )
            with gzip.GzipFile(fileobj=source) as compressed:
                size = 0
                while chunk := compressed.read(
                    min(64 * 1024, EXPANDED_MAX_BYTES - size + 1)
                ):
                    size += len(chunk)
                    if size > EXPANDED_MAX_BYTES:
                        raise ArchiveLimitError(
                            f"Expanded archive exceeds {EXPANDED_MAX_BYTES} bytes"
                        )
                    expanded.write(chunk)
            expanded.seek(0)
            buffered = stack.enter_context(_TarReader(expanded))
            archive = stack.enter_context(
                tarfile.open(fileobj=buffered, mode="r:", tarinfo=_StrictTarInfo)
            )
        files: ArchiveFiles = {}
        paths: set[str] = set()
        index_bytes = 0
        directories: set[str] = set()
        budget = _ReadBudget()
        members = (
            archive.infolist() if isinstance(archive, zipfile.ZipFile) else archive
        )
        for index, member in enumerate(members, 1):
            # The member's headers are parsed; the next member starts a new budget.
            if buffered is not None:
                buffered.member_metadata_bytes = 0
            if index > ARCHIVE_MAX_ENTRIES:
                raise ArchiveLimitError(
                    f"Archive exceeds {ARCHIVE_MAX_ENTRIES} entries"
                )
            if isinstance(member, zipfile.ZipInfo):
                if member.flag_bits & 0x61 or member.compress_type not in (
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                ):
                    raise ArchiveLimitError(
                        "Archive ZIP compression, encryption or patched data is not supported"
                    )
                name = member.orig_filename
                mode = stat.S_IFMT(member.external_attr >> 16)
                regular = mode in (0, stat.S_IFREG, stat.S_IFDIR)
                is_dir = member.is_dir() and regular
            else:
                if member.issparse():
                    raise ArchiveLimitError(
                        "Archive TAR sparse members are not supported"
                    )
                name, is_dir = member.name, member.isdir()
                regular = member.isfile() or is_dir
                index_bytes += sys.getsizeof(member.pax_headers) + sum(
                    sys.getsizeof(key) + sys.getsizeof(value)
                    for key, value in member.pax_headers.items()
                )
            path = archive_path(name)
            parents = {path.rsplit("/", i)[0] for i in range(1, path.count("/") + 1)}
            if (
                path in paths
                or (not is_dir and path in directories)
                or parents.intersection(files)
            ):
                raise ValueError(f"Duplicate or conflicting archive path: {path}")
            index_bytes += len(path.encode()) + sum(
                len(parent.encode()) for parent in parents - directories
            )
            if index_bytes > ARCHIVE_INDEX_MAX_BYTES:
                raise ArchiveLimitError("Archive index is too large")
            if not path:
                if is_dir:
                    continue
                raise ValueError(f"Empty archive member: {name!r}")
            paths.add(path)
            directories.update(parents)
            if is_dir:
                directories.add(path)
            elif regular:
                files[path] = partial(_open_member, archive, member, budget)
            else:
                files[path] = None
        if buffered is not None:
            buffered.metadata_reads = False
        _require_complete_catalog(archive, data, required=require_complete)
        # Directories named like files must not silently select a fallback manifest.
        for path in directories:
            if path == "SKILL.md" or path.endswith((".json", "/SKILL.md")):
                files[path] = None
        yield files
