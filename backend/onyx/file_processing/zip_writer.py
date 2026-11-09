"""Write a ZIP with the bytes of zipfile.ZipFile(file, "w", ZIP_DEFLATED).

zipfile keeps a ZipInfo for each written entry until it writes the central
directory, so memory grows with the entry count. SpooledZipWriter writes the
same local headers, data, central directory and end records with struct and
the documented zlib, bz2 and lzma compressors, and keeps the central
directory fields in SQLite until close.

The output must be seekable, as for zipfile without data descriptors.
"""

import bz2
import io
import lzma
import struct
import time
import zipfile
import zlib
from collections.abc import Buffer, Callable
from types import TracebackType
from typing import IO, Literal, Protocol, Self

from onyx.db.zip_metadata import SpooledZipInfos

# APPNOTE 4.3.7, 4.3.12, 4.3.14, 4.3.15 and 4.3.16, as in zipfile's structs.
_LOCAL_HEADER = struct.Struct("<4s2B4HL2L2H")
_RECORD = struct.Struct("<4s4B4HL2L5H2L")
_ZIP64_END = struct.Struct("<4sQ2H2L4Q")
_ZIP64_LOCATOR = struct.Struct("<4sLQL")
_END = struct.Struct("<4s4H2LH")
_ZIP64_LIMIT = (1 << 31) - 1
_FILE_COUNT_LIMIT = (1 << 16) - 1
_ZIP64_VERSION = 45
_BZIP2_VERSION = 46
_LZMA_VERSION = 63
_UTF8_NAME = 1 << 11
_LZMA_END_MARKER = 1 << 1
_ZIP64_EXTRA = 0x0001
# zipfile's LZMA header: version 9.4 and the LZMA1 properties of preset 6.
_LZMA_HEADER = (
    struct.pack("<BBH", 9, 4, 5) + bytes([2 * 45 + 3]) + (1 << 23).to_bytes(4, "little")
)
_LZMA_FILTER = {
    "id": lzma.FILTER_LZMA1,
    "lc": 3,
    "lp": 0,
    "pb": 2,
    "dict_size": 1 << 23,
}


class _Compressor(Protocol):
    def compress(self, data: Buffer, /) -> bytes: ...

    def flush(self) -> bytes: ...


class _LzmaCompressor(_Compressor):
    def __init__(self) -> None:
        self._compressor = lzma.LZMACompressor(lzma.FORMAT_RAW, filters=[_LZMA_FILTER])
        self._header = _LZMA_HEADER

    def compress(self, data: Buffer, /) -> bytes:
        header, self._header = self._header, b""
        return header + self._compressor.compress(data)

    def flush(self) -> bytes:
        header, self._header = self._header, b""
        return header + self._compressor.flush()


def _compressor(info: zipfile.ZipInfo) -> _Compressor | None:
    level = info.compress_level
    if info.compress_type == zipfile.ZIP_STORED:
        return None
    if info.compress_type == zipfile.ZIP_DEFLATED:
        return zlib.compressobj(
            zlib.Z_DEFAULT_COMPRESSION if level is None else level, zlib.DEFLATED, -15
        )
    if info.compress_type == zipfile.ZIP_BZIP2:
        return bz2.BZ2Compressor() if level is None else bz2.BZ2Compressor(level)
    if info.compress_type == zipfile.ZIP_LZMA:
        return _LzmaCompressor()
    raise NotImplementedError("That compression method is not supported")


def _dos_time(info: zipfile.ZipInfo) -> tuple[int, int]:
    year, month, day, hour, minute, second = info.date_time
    return hour << 11 | minute << 5 | second // 2, (year - 1980) << 9 | month << 5 | day


def _name_and_flags(info: zipfile.ZipInfo) -> tuple[bytes, int]:
    encoding = "ascii" if info.flag_bits & _UTF8_NAME else "cp437"
    try:
        return info.filename.encode(encoding), info.flag_bits & ~_UTF8_NAME
    except UnicodeEncodeError:
        return info.filename.encode("utf-8"), info.flag_bits | _UTF8_NAME


def _min_version(info: zipfile.ZipInfo, zip64: bool) -> int:
    version = _ZIP64_VERSION if zip64 else 0
    if info.compress_type == zipfile.ZIP_BZIP2:
        return max(_BZIP2_VERSION, version)
    if info.compress_type == zipfile.ZIP_LZMA:
        return max(_LZMA_VERSION, version)
    return version


def _local_header(info: zipfile.ZipInfo, zip64: bool) -> bytes:
    """ZipInfo.FileHeader, which also raises the entry's versions."""
    extra = info.extra
    file_size, compress_size = info.file_size, info.compress_size
    if zip64:
        extra += struct.pack("<HHQQ", _ZIP64_EXTRA, 16, file_size, compress_size)
        file_size = compress_size = 0xFFFFFFFF
    version = _min_version(info, zip64)
    info.extract_version = max(version, info.extract_version)
    info.create_version = max(version, info.create_version)
    name, flags = _name_and_flags(info)
    dos_time, dos_date = _dos_time(info)
    header = _LOCAL_HEADER.pack(
        b"PK\x03\x04",
        info.extract_version,
        info.reserved,
        flags,
        info.compress_type,
        dos_time,
        dos_date,
        info.CRC,
        compress_size,
        file_size,
        len(name),
        len(extra),
    )
    return header + name + extra


def _without_zip64_extra(extra: bytes) -> bytes:
    """Remove ZIP64 fields as zipfile's _Extra.strip does, short tails kept."""
    kept: list[bytes] = []
    while extra:
        if len(extra) < 4:
            field_id: int | None = None
            length = 0
        else:
            field_id, length = struct.unpack("<HH", extra[:4])
        field, extra = extra[: 4 + length], extra[4 + length :]
        if field_id != _ZIP64_EXTRA:
            kept.append(field)
    return b"".join(kept)


def _record(info: zipfile.ZipInfo) -> bytes:
    zip64_values: list[int] = []
    file_size, compress_size = info.file_size, info.compress_size
    if file_size > _ZIP64_LIMIT or compress_size > _ZIP64_LIMIT:
        zip64_values += [file_size, compress_size]
        file_size = compress_size = 0xFFFFFFFF
    header_offset = info.header_offset
    if header_offset > _ZIP64_LIMIT:
        zip64_values.append(header_offset)
        header_offset = 0xFFFFFFFF
    extra = info.extra
    if zip64_values:
        extra = struct.pack(
            "<HH" + "Q" * len(zip64_values),
            _ZIP64_EXTRA,
            8 * len(zip64_values),
            *zip64_values,
        ) + _without_zip64_extra(extra)
    version = _min_version(info, bool(zip64_values))
    name, flags = _name_and_flags(info)
    dos_time, dos_date = _dos_time(info)
    record = _RECORD.pack(
        b"PK\x01\x02",
        max(version, info.create_version),
        info.create_system,
        max(version, info.extract_version),
        info.reserved,
        flags,
        info.compress_type,
        dos_time,
        dos_date,
        info.CRC,
        compress_size,
        file_size,
        len(name),
        len(extra),
        len(info.comment),
        0,
        info.internal_attr,
        info.external_attr,
        header_offset,
    )
    return record + name + extra + info.comment


class _MemberWriter(io.BufferedIOBase):
    """zipfile's member writer: compress, then rewrite the local header."""

    def __init__(
        self,
        output: IO[bytes],
        info: zipfile.ZipInfo,
        zip64: bool,
        compressor: _Compressor | None,
        on_close: Callable[[zipfile.ZipInfo | None], None],
    ) -> None:
        self._output = output
        self._info = info
        self._zip64 = zip64
        self._on_close = on_close
        self._compressor = compressor
        self._file_size = 0
        self._compress_size = 0
        self._crc = 0

    @property
    def name(self) -> str:
        return self._info.filename

    @property
    def mode(self) -> str:
        return "wb"

    def writable(self) -> bool:
        return True

    def write(self, data: Buffer, /) -> int:
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        view = memoryview(data)
        self._file_size += view.nbytes
        self._crc = zlib.crc32(view, self._crc)
        if self._compressor is not None:
            compressed = self._compressor.compress(view)
            self._compress_size += len(compressed)
            self._output.write(compressed)
        else:
            self._output.write(view)
        return view.nbytes

    def close(self) -> None:
        if self.closed:
            return
        written: zipfile.ZipInfo | None = None
        try:
            super().close()
            info = self._info
            if self._compressor is not None:
                tail = self._compressor.flush()
                self._compress_size += len(tail)
                self._output.write(tail)
                info.compress_size = self._compress_size
            else:
                info.compress_size = self._file_size
            info.CRC = self._crc
            info.file_size = self._file_size
            if not self._zip64:
                if self._file_size > _ZIP64_LIMIT:
                    raise RuntimeError("File size too large, try using force_zip64")
                if self._compress_size > _ZIP64_LIMIT:
                    raise RuntimeError(
                        "Compressed size too large, try using force_zip64"
                    )
            end = self._output.tell()
            self._output.seek(info.header_offset)
            self._output.write(_local_header(info, self._zip64))
            self._output.seek(end)
            written = info
        finally:
            self._on_close(written)


class SpooledZipWriter:
    """Write ZIP members with a disk-backed directory and no read interface.

    It does not warn about duplicate names; callers reject them first.
    """

    def __init__(self, file: IO[bytes]) -> None:
        if not file.seekable():
            raise ValueError("SpooledZipWriter needs a seekable output")
        self._output = file
        self._directory_start = file.tell()
        self._entries = SpooledZipInfos()
        self._writing = False
        self._closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _member_closed(self, info: zipfile.ZipInfo | None) -> None:
        try:
            if info is not None:
                self._directory_start = self._output.tell()
                self._entries.append(info)
        finally:
            self._writing = False

    def open(
        self, info: zipfile.ZipInfo, mode: Literal["w"] = "w"
    ) -> io.BufferedIOBase:
        """Start a member, as ZipFile.open(info, "w") does."""
        if mode != "w":
            raise ValueError('open() requires mode "w"')
        if self._closed:
            raise ValueError("Attempt to use ZIP archive that was already closed")
        if self._writing:
            raise ValueError(
                "Can't write to the ZIP file while there is another write handle "
                "open on it. Close the first handle before opening another."
            )
        info.compress_size = 0
        info.CRC = 0
        info.flag_bits = _UTF8_NAME
        if info.compress_type == zipfile.ZIP_LZMA:
            info.flag_bits |= _LZMA_END_MARKER
        if not info.external_attr:
            info.external_attr = 0o600 << 16
        # Compressed data can be larger than the input.
        zip64 = info.file_size * 1.05 > _ZIP64_LIMIT
        self._output.seek(self._directory_start)
        info.header_offset = self._output.tell()
        compressor = _compressor(info)
        self._output.write(_local_header(info, zip64))
        member = _MemberWriter(
            self._output, info, zip64, compressor, self._member_closed
        )
        self._writing = True
        return member

    def writestr(self, info: zipfile.ZipInfo | str, data: str | bytes) -> None:
        """Write one member, as ZipFile.writestr() does."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        if isinstance(info, str):
            name = info
            info = zipfile.ZipInfo(name, date_time=time.localtime(time.time())[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            if info.is_dir():
                info.external_attr = 0o40775 << 16 | 0x10
            else:
                info.external_attr = 0o600 << 16
        if self._closed:
            raise ValueError("Attempt to write to ZIP archive that was already closed")
        if self._writing:
            raise ValueError(
                "Can't write to ZIP archive while an open writing handle exists."
            )
        info.file_size = len(data)
        with self.open(info) as member:
            member.write(data)

    def close(self) -> None:
        """Write the central directory and end records once."""
        if self._closed:
            return
        if self._writing:
            raise ValueError(
                "Can't close the ZIP file while there is an open writing handle "
                "on it. Close the writing handle before closing the zip."
            )
        try:
            self._output.seek(self._directory_start)
            self._write_end()
        finally:
            self._closed = True
            self._entries.close()

    def _write_end(self) -> None:
        output = self._output
        for info in self._entries:
            output.write(_record(info))
        end = output.tell()
        count = len(self._entries)
        size = end - self._directory_start
        offset = self._directory_start
        if count > _FILE_COUNT_LIMIT or offset > _ZIP64_LIMIT or size > _ZIP64_LIMIT:
            output.write(
                _ZIP64_END.pack(
                    b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, offset
                )
            )
            output.write(_ZIP64_LOCATOR.pack(b"PK\x06\x07", 0, end, 1))
            count = min(count, 0xFFFF)
            size = min(size, 0xFFFFFFFF)
            offset = min(offset, 0xFFFFFFFF)
        output.write(_END.pack(b"PK\x05\x06", 0, 0, count, count, size, offset, 0))
        output.flush()
