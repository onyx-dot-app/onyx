"""Bounded, seekable access to repository archives without extracting paths."""

import gzip
import io
import stat
import tarfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from functools import partial
from tempfile import SpooledTemporaryFile
from typing import IO, cast

ARCHIVE_MAX_BYTES = 25 * 1024 * 1024
ARCHIVE_MAX_ENTRIES = 10_000
MANIFEST_MAX_BYTES = 1024 * 1024
# Independent processing ceilings, not per-skill validation limits.
EXPANDED_MAX_BYTES = 1024 * 1024 * 1024
MEMBER_READ_MAX_BYTES = 1024 * 1024 * 1024
SPOOL_MEMORY_BYTES = 1024 * 1024

type ArchiveFiles = dict[str, Callable[[], IO[bytes]] | None]


class ArchiveLimitError(ValueError):
    """The whole read failed; callers must not infer removed entries."""


def archive_path(value: str) -> str:
    if value in ("", ".", "./"):
        return ""
    value = value.removeprefix("./").removesuffix("/")
    if (
        any(c in value for c in ("\\", "\x00"))
        or any(part in ("", ".", "..") for part in value.split("/"))
        or (len(value) >= 3 and value[0].isalpha() and value[1:3] == ":/")
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


class _MemberReader(io.BufferedReader):
    def __init__(self, source: io.BufferedIOBase, budget: _ReadBudget) -> None:
        super().__init__(source)
        self.budget = budget

    def read(self, size: int | None = -1, /) -> bytes:
        requested = (
            self.budget.remaining + 1
            if size is None or size < 0
            else min(size, self.budget.remaining + 1)
        )
        data = super().read(requested)
        self.budget.consume(len(data))
        return data


class _TarReader(io.BufferedReader):
    def read(self, size: int | None = -1, /) -> bytes:
        # tarfile reads extension headers in one allocation.
        if size is None or size < 0 or size > MANIFEST_MAX_BYTES:
            raise ArchiveLimitError("Archive metadata is too large")
        return super().read(size)


def _open_member(
    archive: zipfile.ZipFile | tarfile.TarFile,
    member: zipfile.ZipInfo | tarfile.TarInfo,
    budget: _ReadBudget,
) -> IO[bytes]:
    if isinstance(archive, zipfile.ZipFile) and isinstance(member, zipfile.ZipInfo):
        source = archive.open(member)
    elif isinstance(archive, tarfile.TarFile) and isinstance(member, tarfile.TarInfo):
        source = archive.extractfile(member)
        if source is None:
            raise ValueError(f"Unreadable archive member: {member.name}")
    else:
        raise TypeError("Archive member format mismatch")
    return _MemberReader(cast(io.BufferedIOBase, source), budget)


@contextmanager
def archive_files(data: bytes) -> Iterator[ArchiveFiles]:
    if len(data) > ARCHIVE_MAX_BYTES:
        raise ArchiveLimitError(f"Archive exceeds {ARCHIVE_MAX_BYTES} bytes")
    with ExitStack() as stack:
        source = stack.enter_context(io.BytesIO(data))
        archive: zipfile.ZipFile | tarfile.TarFile
        if zipfile.is_zipfile(source):
            archive = stack.enter_context(zipfile.ZipFile(source))
        else:
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
            archive = stack.enter_context(tarfile.open(fileobj=buffered, mode="r:"))
        files: ArchiveFiles = {}
        paths: set[str] = set()
        directories: set[str] = set()
        budget = _ReadBudget()
        members = (
            archive.infolist() if isinstance(archive, zipfile.ZipFile) else archive
        )
        for index, member in enumerate(members, 1):
            if index > ARCHIVE_MAX_ENTRIES:
                raise ArchiveLimitError(
                    f"Archive exceeds {ARCHIVE_MAX_ENTRIES} entries"
                )
            if isinstance(member, zipfile.ZipInfo):
                name, is_dir = member.orig_filename, member.is_dir()
                mode = stat.S_IFMT(member.external_attr >> 16)
                regular = mode in (0, stat.S_IFREG, stat.S_IFDIR)
            else:
                name, is_dir = member.name, member.isdir()
                regular = member.isfile() and not member.issparse() or is_dir
            path = archive_path(name)
            if not path:
                if is_dir:
                    continue
                raise ValueError(f"Empty archive member: {name!r}")
            if path in paths or (not is_dir and path in directories):
                raise ValueError(f"Duplicate or conflicting archive path: {path}")
            parents = {path.rsplit("/", i)[0] for i in range(1, path.count("/") + 1)}
            if parents.intersection(files):
                raise ValueError(f"Conflicting archive path: {path}")
            paths.add(path)
            directories.update(parents)
            if is_dir:
                directories.add(path)
            elif regular:
                files[path] = partial(_open_member, archive, member, budget)
            else:
                files[path] = None
        # Directories named like files must not silently select a fallback manifest.
        for path in directories:
            if path.endswith((".json", "/SKILL.md")):
                files[path] = None
        yield files
