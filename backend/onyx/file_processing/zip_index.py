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
import struct
import zipfile
from collections.abc import Iterator
from functools import cache
from types import TracebackType
from typing import IO, Literal, Self
from zlib import crc32

from onyx.db.zip_metadata import ZipEntryStore
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
        try:
            self._entries_store = ZipEntryStore()
        except BaseException:
            self._archive.close()
            raise
        try:
            size = self._archive.directory_size
            if max_metadata_bytes is not None and size > max_metadata_bytes:
                raise ZipMetadataLimitError("Zip metadata is too large")
            start = self._archive.directory_start
            self._directory = memoryview(data)[start : start + size]
            self._entries_store.populate(
                (
                    (seq, info.filename.encode(), offset, info.header_offset)
                    for seq, (offset, info) in enumerate(self._records())
                ),
                directory_start=start,
                shared_header_order=_zipfile_shared_header_order(),
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
        self._entries_store.close()
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

    def _entry(self, record: int, end_offset: int) -> zipfile.ZipInfo:
        info, _ = self._parse(record)
        info._end_offset = end_offset  # ty: ignore[unresolved-attribute]
        return info

    def infos(self) -> Iterator[zipfile.ZipInfo]:
        """Entries in central directory order, as ZipFile.infolist()."""
        for record, end_offset in self._entries_store.entries():
            yield self._entry(record, end_offset)

    def sorted_infos(self) -> Iterator[zipfile.ZipInfo]:
        """Entries sorted by filename, ties in directory order."""
        # UTF-8 byte order is code point order, so this matches sorting str.
        for record, end_offset in self._entries_store.entries(by_name=True):
            yield self._entry(record, end_offset)

    def getinfo(self, name: str) -> zipfile.ZipInfo:
        """The last entry with this name, as ZipFile.getinfo()."""
        row = self._entries_store.find(name)
        if row is None:
            raise KeyError(f"There is no item named {name!r} in the archive")
        return self._entry(*row)

    def open(self, info: zipfile.ZipInfo) -> IO[bytes]:
        return self._archive.open(info)

    def read(self, name: str) -> bytes:
        with self.open(self.getinfo(name)) as source:
            return source.read()
