"""ZIP access that does not hold one object for each central directory entry.

zipfile.ZipFile reads the whole central directory into memory and keeps a
ZipInfo for each entry, so a small archive with many entries, long names,
extra fields or comments can use much more memory than its size.
ZipIndex parses one central directory record at a time from the input bytes
and keeps only each entry's name and offsets in an anonymous SQLite database,
a temp file that the OS removes, as GroupedRowStore does.

This module owns the parsing of the end records, the central directory records
and the local headers, and zip_stream reads member data. Both use documented
interfaces only. They give the same checks, errors and ZipInfo values as
zipfile on the running Python, with one exception: entries that share a local
header offset (see _END_OFFSETS in onyx.db.zip_metadata). The ZIP64 end record
checks changed in a 3.13 patch release (gh-139700), so a zipfile probe with no
side effects selects them.
"""

import io
import struct
import warnings
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from types import TracebackType
from typing import Self
from zlib import crc32

from onyx.db.zip_metadata import ZipEntryStore
from onyx.file_processing.zip_limits import ZipMetadataLimitError
from onyx.file_processing.zip_stream import ZipMemberReader

# APPNOTE 4.3.16, 4.3.15, 4.3.14, 4.3.12 and 4.3.7, as in zipfile's structs.
_END = struct.Struct("<4s4H2LH")
_ZIP64_LOCATOR = struct.Struct("<4sLQL")
_ZIP64_END = struct.Struct("<4sQ2H2L4Q")
_RECORD = struct.Struct("<4s4B4HL2L5H2L")
_LOCAL_HEADER = struct.Struct("<4s2B4HL2L2H")
_END_SIGNATURE = b"PK\x05\x06"
_ZIP64_LOCATOR_SIGNATURE = b"PK\x06\x07"
_ZIP64_END_SIGNATURE = b"PK\x06\x06"
_RECORD_SIGNATURE = b"PK\x01\x02"
_LOCAL_HEADER_SIGNATURE = b"PK\x03\x04"
_MAX_COMMENT = (1 << 16) - 1
_MAX_EXTRACT_VERSION = 63
_ENCRYPTED = 1 << 0
_COMPRESSED_PATCH = 1 << 5
_STRONG_ENCRYPTION = 1 << 6
_UTF8_NAME = 1 << 11
_ZIP64_EXTRA = 0x0001
_UNICODE_PATH_EXTRA = 0x7075


class IndexedZipInfo(zipfile.ZipInfo):
    """A ZipInfo from a ZipIndex.

    ``directory_name`` is the decoded central directory name, before any
    Unicode path field or name cleanup; local headers must match it.
    ``end_offset`` is where the entry's data must end.
    """

    __slots__ = ("directory_name", "end_offset")
    directory_name: str
    end_offset: int

    def __repr__(self) -> str:
        # Errors that name an entry stay the same as zipfile's.
        return super().__repr__().replace(type(self).__name__, "ZipInfo", 1)


@cache
def _checks_zip64_end() -> bool:
    """Whether zipfile checks the ZIP64 end record (gh-139700).

    The probe is an empty ZIP64 archive whose record declares a wrong size.
    It changes no process state, so concurrent first calls are safe.
    """
    record = _ZIP64_END.pack(_ZIP64_END_SIGNATURE, 45, 45, 45, 0, 0, 0, 0, 0, 0)
    locator = _ZIP64_LOCATOR.pack(_ZIP64_LOCATOR_SIGNATURE, 0, 0, 1)
    end = _END.pack(_END_SIGNATURE, 0, 0, 0, 0, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    try:
        zipfile.ZipFile(io.BytesIO(record + locator + end)).close()
    except zipfile.BadZipFile:
        return True
    return False


@cache
def _comment_search_window() -> int:
    """Match the runtime's acceptance of trailing bytes after the end record."""
    end = _END.pack(_END_SIGNATURE, 0, 0, 0, 0, 0, 0, 0)
    try:
        zipfile.ZipFile(io.BytesIO(end + bytes(_MAX_COMMENT + 1))).close()
    except zipfile.BadZipFile:
        return _MAX_COMMENT
    return _MAX_COMMENT + 1


@dataclass(frozen=True)
class _Directory:
    start: int
    size: int
    concat: int


def _end_record(data: bytes) -> tuple[tuple[int, ...], int] | None:
    """The end record fields and offset, found as zipfile finds them."""
    record = data[-_END.size :]
    if (
        len(record) == _END.size
        and record.startswith(_END_SIGNATURE)
        and record.endswith(b"\0\0")
    ):
        return _END.unpack(record), len(data) - _END.size
    # The comment may hold up to 64 KiB; the last signature wins.
    search_start = max(len(data) - _comment_search_window() - _END.size, 0)
    found = data.rfind(_END_SIGNATURE, search_start)
    if found < 0:
        return None
    record = data[found : found + _END.size]
    if len(record) != _END.size:
        return None
    return _END.unpack(record), found


def _zip64_directory(
    data: bytes, end_location: int, checked: bool
) -> tuple[int, int, int] | None:
    """(size, offset, location) from the ZIP64 records, or None if absent."""
    locator_offset = end_location - _ZIP64_LOCATOR.size
    if checked and locator_offset < 0:
        return None
    # Python 3.13.0 seeks from the end of the file, which stops at 0. The end
    # record follows, so the slice always holds a whole locator.
    locator_start = max(locator_offset, 0)
    locator = data[locator_start : locator_start + _ZIP64_LOCATOR.size]
    signature, disk, relative_offset, disks = _ZIP64_LOCATOR.unpack(locator)
    if signature != _ZIP64_LOCATOR_SIGNATURE:
        return None
    if disk != 0 or disks > 1:
        raise zipfile.BadZipFile("zipfiles that span multiple disks are not supported")
    record_offset = locator_offset - _ZIP64_END.size
    if not checked:
        # Python 3.13.0 assumes no zip64 extensible data and no record checks.
        record_start = max(record_offset, 0)
        record = data[record_start : record_start + _ZIP64_END.size]
        if len(record) != _ZIP64_END.size or not record.startswith(
            _ZIP64_END_SIGNATURE
        ):
            return None
        fields = _ZIP64_END.unpack(record)
        # Python 3.13.0 takes both ZIP64 records out of concat.
        location = end_location - _ZIP64_END.size - _ZIP64_LOCATOR.size
        return fields[8], fields[9], location
    if relative_offset > record_offset:
        raise zipfile.BadZipFile("Corrupt zip64 end of central directory locator")
    # First assume no prepended data, then no zip64 extensible data.
    extensible_size = record_offset - relative_offset
    record = data[relative_offset : relative_offset + _ZIP64_END.size]
    if not record.startswith(_ZIP64_END_SIGNATURE) and relative_offset != record_offset:
        extensible_size = 0
        record = data[record_offset : record_offset + _ZIP64_END.size]
    if not record.startswith(_ZIP64_END_SIGNATURE):
        raise zipfile.BadZipFile("Zip64 end of central directory record not found")
    fields = _ZIP64_END.unpack(record)
    size, offset = fields[8], fields[9]
    if (
        offset + size != relative_offset
        or fields[1] + 12 != _ZIP64_END.size + extensible_size
    ):
        raise zipfile.BadZipFile("Corrupt zip64 end of central directory record")
    return size, offset, record_offset - extensible_size


def _directory(data: bytes, checked_zip64_end: bool) -> _Directory:
    """Locate the central directory as zipfile.ZipFile does."""
    found = _end_record(data)
    if found is None:
        raise zipfile.BadZipFile("File is not a zip file")
    fields, location = found
    size, offset = fields[5], fields[6]
    zip64 = _zip64_directory(data, location, checked_zip64_end)
    if zip64 is not None:
        size, offset, location = zip64
    # "concat" is the length of any data prepended to the archive.
    concat = location - size - offset
    start = offset + concat
    if start < 0:
        raise zipfile.BadZipFile("Bad offset for central directory")
    return _Directory(start=start, size=size, concat=concat)


def _decode_extra(info: zipfile.ZipInfo, name_crc: int, *, warn: bool) -> None:
    """Apply ZIP64 and Unicode path extra fields as zipfile does.

    zipfile warns once, when it reads the directory; ``warn`` is that pass.
    """
    extra = info.extra
    while len(extra) >= 4:
        kind, length = struct.unpack("<HH", extra[:4])
        if length + 4 > len(extra):
            raise zipfile.BadZipFile(
                "Corrupt extra field %04x (size=%d)" % (kind, length)
            )
        value = extra[4 : length + 4]
        if kind == _ZIP64_EXTRA:
            field = ""
            try:
                if info.file_size in (0xFFFF_FFFF_FFFF_FFFF, 0xFFFF_FFFF):
                    field = "File size"
                    (info.file_size,) = struct.unpack("<Q", value[:8])
                    value = value[8:]
                if info.compress_size == 0xFFFF_FFFF:
                    field = "Compress size"
                    (info.compress_size,) = struct.unpack("<Q", value[:8])
                    value = value[8:]
                if info.header_offset == 0xFFFF_FFFF:
                    field = "Header offset"
                    (info.header_offset,) = struct.unpack("<Q", value[:8])
            except struct.error:
                raise zipfile.BadZipFile(
                    f"Corrupt zip64 extra field. {field} not found."
                ) from None
        elif kind == _UNICODE_PATH_EXTRA:
            try:
                version, crc = struct.unpack("<BL", value[:5])
                if version == 1 and crc == name_crc:
                    unicode_name = value[5:].decode("utf-8")
                    if unicode_name:
                        # ZipInfo sanitizes the name as zipfile does.
                        info.filename = zipfile.ZipInfo(unicode_name).filename
                    elif warn:
                        warnings.warn(
                            "Empty unicode path extra field (0x7075)", stacklevel=2
                        )
            except struct.error as exc:
                raise zipfile.BadZipFile(
                    "Corrupt unicode path extra field (0x7075)"
                ) from exc
            except UnicodeDecodeError as exc:
                raise zipfile.BadZipFile(
                    "Corrupt unicode path extra field (0x7075): invalid utf-8 bytes"
                ) from exc
        extra = extra[length + 4 :]


class ZipIndex:
    """Read a ZIP from bytes with memory that does not grow with its entries.

    Callers keep the input bytes. ``max_metadata_bytes`` refuses a central
    directory larger than that before any record is parsed.
    """

    def __init__(self, data: bytes, *, max_metadata_bytes: int | None = None) -> None:
        self._data: bytes | None = data
        directory = _directory(data, _checks_zip64_end())
        if max_metadata_bytes is not None and directory.size > max_metadata_bytes:
            raise ZipMetadataLimitError("Zip metadata is too large")
        self._concat = directory.concat
        self._directory_size = directory.size
        self._directory = memoryview(data)[
            directory.start : directory.start + directory.size
        ]
        self._entries_store = ZipEntryStore()
        try:
            self._entries_store.populate(
                (
                    (seq, info.filename.encode(), offset, info.header_offset)
                    for seq, (offset, info) in enumerate(self._records())
                ),
                directory_start=directory.start,
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
        self._directory.release()
        self._data = None

    def _records(self) -> Iterator[tuple[int, IndexedZipInfo]]:
        # zipfile stops when the declared size is consumed; short data truncates.
        offset = 0
        while offset < self._directory_size:
            info, length = self._parse(offset, warn=True)
            yield offset, info
            offset += length

    def _parse(self, offset: int, *, warn: bool) -> tuple[IndexedZipInfo, int]:
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
        name = raw_name.decode("utf-8" if fields[5] & _UTF8_NAME else "cp437")
        info = IndexedZipInfo(name)
        info.directory_name = name
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
        info.date_time = (
            (date >> 9) + 1980,
            (date >> 5) & 0xF,
            date & 0x1F,
            time >> 11,
            (time >> 5) & 0x3F,
            (time & 0x1F) * 2,
        )
        _decode_extra(info, crc32(raw_name), warn=warn)
        info.header_offset += self._concat
        return info, _RECORD.size + fields[12] + fields[13] + fields[14]

    def _entry(self, record: int, end_offset: int) -> IndexedZipInfo:
        info, _ = self._parse(record, warn=False)
        info.end_offset = end_offset
        return info

    def infos(self) -> Iterator[IndexedZipInfo]:
        """Entries in central directory order, as ZipFile.infolist()."""
        for record, end_offset in self._entries_store.entries():
            yield self._entry(record, end_offset)

    def sorted_infos(self) -> Iterator[IndexedZipInfo]:
        """Entries sorted by filename, ties in directory order."""
        # UTF-8 byte order is code point order, so this matches sorting str.
        for record, end_offset in self._entries_store.entries(by_name=True):
            yield self._entry(record, end_offset)

    def getinfo(self, name: str) -> IndexedZipInfo:
        """The last entry with this name, as ZipFile.getinfo()."""
        row = self._entries_store.find(name)
        if row is None:
            raise KeyError(f"There is no item named {name!r} in the archive")
        return self._entry(*row)

    def open(self, info: IndexedZipInfo) -> ZipMemberReader:
        """Open a member for reading, with the checks of ZipFile.open()."""
        return self._open(info, info)

    def read(self, name: str) -> bytes:
        with self._open(self.getinfo(name), name) as source:
            return source.read()

    def _open(self, info: IndexedZipInfo, requested: object) -> ZipMemberReader:
        if self._data is None:
            raise ValueError("Attempt to use ZIP archive that was already closed")
        source = io.BytesIO(self._data)
        try:
            source.seek(info.header_offset)
            header = source.read(_LOCAL_HEADER.size)
            if len(header) != _LOCAL_HEADER.size:
                raise zipfile.BadZipFile("Truncated file header")
            fields = _LOCAL_HEADER.unpack(header)
            if fields[0] != _LOCAL_HEADER_SIGNATURE:
                raise zipfile.BadZipFile("Bad magic number for file header")
            name = source.read(fields[10])
            if fields[11]:
                source.seek(fields[11], io.SEEK_CUR)
            if info.flag_bits & _COMPRESSED_PATCH:
                raise NotImplementedError("compressed patched data (flag bit 5)")
            if info.flag_bits & _STRONG_ENCRYPTION:
                raise NotImplementedError("strong encryption (flag bit 6)")
            decoded = name.decode("utf-8" if fields[3] & _UTF8_NAME else "cp437")
            if decoded != info.directory_name:
                raise zipfile.BadZipFile(
                    "File name in directory %r and header %r differ."
                    % (info.directory_name, name)
                )
            if source.tell() + info.compress_size > info.end_offset:
                raise zipfile.BadZipFile(
                    f"Overlapped entries: {info.directory_name!r} (possible zip bomb)"
                )
            if info.flag_bits & _ENCRYPTED:
                raise RuntimeError(
                    "File %r is encrypted, password required for extraction"
                    % (requested,)
                )
            return ZipMemberReader(source, info)
        except BaseException:
            source.close()
            raise
