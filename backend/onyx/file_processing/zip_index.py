"""ZIP access that does not hold one object for each central directory entry.

zipfile.ZipFile reads the whole central directory into memory and keeps a
ZipInfo for each entry, so a small archive with many entries, long names,
extra fields or comments can use much more memory than its size.
ZipIndex parses one central directory record at a time from the input bytes
and keeps only each entry's name and offsets in an anonymous SQLite database,
a temp file that the OS removes, as GroupedRowStore does. Each record gets
the same checks and the same ZipInfo values as in zipfile, and member reads
use zipfile itself, including its overlapped entry check.
"""

import io
import sqlite3
import struct
import zipfile
from collections.abc import Iterator
from functools import cache
from types import TracebackType
from typing import IO, Literal, Self
from zlib import crc32

from onyx.file_processing.zip_limits import ZipMetadataLimitError

# APPNOTE 4.3.12 central directory header, as in zipfile.structCentralDir.
_RECORD = struct.Struct("<4s4B4HL2L5H2L")
_RECORD_SIGNATURE = b"PK\x01\x02"
_UTF8_NAME = 1 << 11
_MAX_EXTRACT_VERSION = 63
# zipfile._EndRecData fields.
_END_SIZE = 5
_END_OFFSET = 6
_END_LOCATION = 9
_ZIP64_END_SIZE = 56 + 20  # ZIP64 end record and locator.

_SCHEMA = (
    "CREATE TABLE entries (seq INTEGER PRIMARY KEY, name BLOB NOT NULL, "
    "record INTEGER NOT NULL, header INTEGER NOT NULL, end_offset INTEGER);"
    "CREATE INDEX entries_by_name ON entries (name, seq);"
    "CREATE INDEX entries_by_header ON entries (header, seq);"
)


@cache
def _zipfile_shared_header_order() -> Literal["ASC", "DESC"]:
    """Probe the two tie orders used by supported zipfile patch releases."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as writer:
        writer.writestr("a", b"")
        writer.writestr("b", b"")
    data = bytearray(output.getvalue())
    second_record = writer.start_dir + _RECORD.size + 1
    struct.pack_into("<L", data, second_record + 42, 0)
    with zipfile.ZipFile(io.BytesIO(data)) as reader:
        first = reader.infolist()[0]
        end_offset = first._end_offset  # ty: ignore[unresolved-attribute]
        return "DESC" if end_offset else "ASC"


# Each entry ends at the next header, with the runtime's tie order.
_END_OFFSETS = (
    "UPDATE entries SET end_offset = COALESCE(later.header, ?) FROM "  # noqa: S608 -- fixed ASC/DESC keywords only
    "(SELECT seq, LEAD(header) OVER (ORDER BY header, seq {order}) AS header "
    "FROM entries) AS later WHERE entries.seq = later.seq"
)


class _EndRecordZipFile(zipfile.ZipFile):
    """A ZipFile that reads only the end record, so it keeps no entry list."""

    directory_start: int
    directory_size: int
    concat: int

    def _RealGetContents(self) -> None:
        # The end record checks of zipfile.ZipFile._RealGetContents.
        source = self.fp
        if source is None:
            raise zipfile.BadZipFile("File is not a zip file")
        try:
            end = zipfile._EndRecData(source)  # ty: ignore[unresolved-attribute]
        except OSError:
            raise zipfile.BadZipFile("File is not a zip file")
        if not end:
            raise zipfile.BadZipFile("File is not a zip file")
        self.directory_size = end[_END_SIZE]
        directory_end = end[_END_LOCATION]
        if end[0] == b"PK\x06\x06":
            # Older helpers leave the location at the ordinary end record.
            source.seek(directory_end)
            if source.read(4) == b"PK\x05\x06":
                directory_end -= _ZIP64_END_SIZE
        self.concat = directory_end - self.directory_size - end[_END_OFFSET]
        self.directory_start = end[_END_OFFSET] + self.concat
        if self.directory_start < 0:
            raise zipfile.BadZipFile("Bad offset for central directory")


class ZipIndex:
    """Read a ZIP from bytes with memory that does not grow with its entries.

    Callers keep the input bytes. ``max_metadata_bytes`` refuses a central
    directory larger than that before any record is parsed.
    """

    def __init__(self, data: bytes, *, max_metadata_bytes: int | None = None) -> None:
        self._archive = _EndRecordZipFile(io.BytesIO(data))
        self._db = sqlite3.connect("")
        try:
            size = self._archive.directory_size
            if max_metadata_bytes is not None and size > max_metadata_bytes:
                raise ZipMetadataLimitError("Zip metadata is too large")
            start = self._archive.directory_start
            self._directory = memoryview(data)[start : start + size]
            self._db.executescript(_SCHEMA)
            with self._db:
                self._db.executemany(
                    "INSERT INTO entries VALUES (?, ?, ?, ?, NULL)",
                    (
                        (seq, info.filename.encode(), offset, info.header_offset)
                        for seq, (offset, info) in enumerate(self._records())
                    ),
                )
                self._db.execute(
                    _END_OFFSETS.format(order=_zipfile_shared_header_order()), (start,)
                )
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()
        self._archive.close()

    def _records(self) -> Iterator[tuple[int, zipfile.ZipInfo]]:
        # zipfile stops when the declared size is consumed; short data truncates.
        offset = 0
        while offset < self._archive.directory_size:
            info, length = self._parse(offset)
            yield offset, info
            offset += length

    def _parse(self, offset: int) -> tuple[zipfile.ZipInfo, int]:
        directory = self._directory
        header = bytes(directory[offset : offset + _RECORD.size])
        if len(header) != _RECORD.size:
            raise zipfile.BadZipFile("Truncated central directory")
        fields = _RECORD.unpack(header)
        if fields[0] != _RECORD_SIGNATURE:
            raise zipfile.BadZipFile("Bad magic number for central directory")
        name_end = offset + _RECORD.size + fields[12]
        extra_end = name_end + fields[13]
        raw_name = bytes(directory[offset + _RECORD.size : name_end])
        info = zipfile.ZipInfo(
            raw_name.decode("utf-8" if fields[5] & _UTF8_NAME else "cp437")
        )
        info.extra = bytes(directory[name_end:extra_end])
        info.comment = bytes(directory[extra_end : extra_end + fields[14]])
        info.header_offset = fields[18]
        (
            info.create_version,
            info.create_system,
            info.extract_version,
            info.reserved,
            info.flag_bits,
            info.compress_type,
            time,
            date,
            info.CRC,
            info.compress_size,
            info.file_size,
        ) = fields[1:12]
        if info.extract_version > _MAX_EXTRACT_VERSION:
            raise NotImplementedError(
                "zip file version %.1f" % (info.extract_version / 10)
            )
        info.volume, info.internal_attr, info.external_attr = fields[15:18]
        info._raw_time = time  # ty: ignore[unresolved-attribute]
        info.date_time = (
            (date >> 9) + 1980,
            (date >> 5) & 0xF,
            date & 0x1F,
            time >> 11,
            (time >> 5) & 0x3F,
            (time & 0x1F) * 2,
        )
        info._decodeExtra(crc32(raw_name))  # ty: ignore[unresolved-attribute]
        info.header_offset += self._archive.concat
        return info, _RECORD.size + fields[12] + fields[13] + fields[14]

    def _entries(self, query: str, *args: object) -> Iterator[zipfile.ZipInfo]:
        for record, end_offset in self._db.execute(query, args):
            info, _ = self._parse(record)
            info._end_offset = end_offset  # ty: ignore[unresolved-attribute]
            yield info

    def infos(self) -> Iterator[zipfile.ZipInfo]:
        """Entries in central directory order, as ZipFile.infolist()."""
        return self._entries("SELECT record, end_offset FROM entries ORDER BY seq")

    def sorted_infos(self) -> Iterator[zipfile.ZipInfo]:
        """Entries sorted by filename, ties in directory order."""
        # UTF-8 byte order is code point order, so this matches sorting str.
        return self._entries(
            "SELECT record, end_offset FROM entries ORDER BY name, seq"
        )

    def getinfo(self, name: str) -> zipfile.ZipInfo:
        """The last entry with this name, as ZipFile.getinfo()."""
        for info in self._entries(
            "SELECT record, end_offset FROM entries WHERE name = ? ORDER BY seq DESC LIMIT 1",
            name.encode(),
        ):
            return info
        raise KeyError(f"There is no item named {name!r} in the archive")

    def open(self, info: zipfile.ZipInfo) -> IO[bytes]:
        return self._archive.open(info)

    def read(self, name: str) -> bytes:
        with self.open(self.getinfo(name)) as source:
            return source.read()


class _SpooledInfos(list[zipfile.ZipInfo]):
    """The written entries of a ZipFile, kept in SQLite until it writes them.

    Each row holds the ZipInfo fields that zipfile writes to the central
    directory.
    """

    def __init__(self) -> None:
        super().__init__()
        self._db = sqlite3.connect("")
        try:
            self._db.execute(
                "CREATE TABLE infos (seq INTEGER PRIMARY KEY, filename, date_time, "
                "flag_bits, comment, compress_size, compress_type, crc, "
                "create_system, create_version, external_attr, extra, "
                "extract_version, file_size, header_offset, internal_attr, reserved)"
            )
        except BaseException:
            self._db.close()
            raise
        self._count = 0

    def append(self, info: zipfile.ZipInfo) -> None:
        self._db.execute(
            "INSERT INTO infos VALUES "
            "(NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                info.filename,
                ",".join(map(str, info.date_time)),
                info.flag_bits,
                info.comment,
                info.compress_size,
                info.compress_type,
                info.CRC,
                info.create_system,
                info.create_version,
                info.external_attr,
                info.extra,
                info.extract_version,
                info.file_size,
                info.header_offset,
                info.internal_attr,
                info.reserved,
            ),
        )
        self._count += 1

    def __len__(self) -> int:
        return self._count

    def __iter__(self) -> Iterator[zipfile.ZipInfo]:
        for row in self._db.execute("SELECT * FROM infos ORDER BY seq"):
            year, month, day, hour, minute, second = map(int, row[2].split(","))
            info = zipfile.ZipInfo(row[1], (year, month, day, hour, minute, second))
            (
                info.flag_bits,
                info.comment,
                info.compress_size,
                info.compress_type,
                info.CRC,
                info.create_system,
                info.create_version,
                info.external_attr,
                info.extra,
                info.extract_version,
                info.file_size,
                info.header_offset,
                info.internal_attr,
                info.reserved,
            ) = row[3:]
            yield info

    def close(self) -> None:
        self._db.close()


class _UnkeptNames(dict[str, zipfile.ZipInfo]):
    def __setitem__(self, name: str, info: zipfile.ZipInfo) -> None:
        pass


class _SpooledZipFile(zipfile.ZipFile):
    """A ZIP writer that keeps written entries in SQLite, not in memory.

    It does not warn about duplicate names; callers reject them first.
    """

    def __init__(self, file: IO[bytes]) -> None:
        super().__init__(file, mode="w", compression=zipfile.ZIP_DEFLATED)
        try:
            self.filelist = _SpooledInfos()
        except BaseException:
            super().close()
            raise
        self.NameToInfo = _UnkeptNames()

    def close(self) -> None:
        try:
            super().close()
        finally:
            infos = self.filelist
            if self.fp is None and isinstance(infos, _SpooledInfos):
                infos.close()


class SpooledZipWriter:
    """Write ZIP members with a disk-backed directory and no read interface."""

    def __init__(self, file: IO[bytes]) -> None:
        self._archive = _SpooledZipFile(file)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def open(self, info: zipfile.ZipInfo, mode: Literal["w"] = "w") -> IO[bytes]:
        return self._archive.open(info, mode=mode)

    def writestr(self, info: zipfile.ZipInfo | str, data: str | bytes) -> None:
        self._archive.writestr(info, data)

    def close(self) -> None:
        self._archive.close()
