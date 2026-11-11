"""Read one ZIP member's data, as zipfile's member stream reads it.

ZipIndex finds and checks the member; this module only decompresses and checks
the CRC. It uses the documented zlib, bz2 and lzma decompressors. The read,
seek and error behavior follows zipfile on Python 3.13.16, whose bzip2 and
LZMA reads are bounded. Encrypted members never get here: ZipIndex refuses them.
"""

import bz2
import io
import lzma
import os
import struct
import zipfile
import zlib
from typing import Protocol

_MAX_N = (1 << 31) - 1
_MIN_READ_SIZE = 4096
_MAX_SEEK_READ = 1 << 24
_LZMA_PROPERTY_SIZE = 5
_LZMA_MAX_PROPERTY_BYTE = (4 * 5 + 4) * 9 + 8
_LZMA_MAX_LITERAL_BITS = 4
_LZMA_OPTIONS_ERROR = "Invalid or unsupported options"


class _Decompressor(Protocol):
    @property
    def eof(self) -> bool: ...

    @property
    def needs_input(self) -> bool: ...

    def decompress(self, data: bytes, max_length: int = -1) -> bytes: ...


def lzma1_properties(properties: bytes) -> dict[str, int]:
    """The LZMA1 filter for a 5-byte properties field, as liblzma decodes it."""
    if len(properties) != _LZMA_PROPERTY_SIZE:
        raise lzma.LZMAError(_LZMA_OPTIONS_ERROR)
    value = properties[0]
    if value > _LZMA_MAX_PROPERTY_BYTE:
        raise lzma.LZMAError(_LZMA_OPTIONS_ERROR)
    literal_context = value % 9
    literal_position = value // 9 % 5
    if literal_context + literal_position > _LZMA_MAX_LITERAL_BITS:
        raise lzma.LZMAError(_LZMA_OPTIONS_ERROR)
    return {
        "id": lzma.FILTER_LZMA1,
        "lc": literal_context,
        "lp": literal_position,
        "pb": value // 45,
        "dict_size": int.from_bytes(properties[1:], "little"),
    }


class _LzmaDecompressor(_Decompressor):
    """APPNOTE 5.8.8: a version, a properties size and properties, then LZMA1."""

    def __init__(self) -> None:
        self._decompressor: lzma.LZMADecompressor | None = None
        self._header = b""
        self._eof = False

    @property
    def eof(self) -> bool:
        return self._eof

    @property
    def needs_input(self) -> bool:
        if self._decompressor is None:
            return True
        return self._decompressor.needs_input

    def decompress(self, data: bytes, max_length: int = -1) -> bytes:
        if self._decompressor is None:
            self._header += data
            if len(self._header) <= 4:
                return b""
            (size,) = struct.unpack("<H", self._header[2:4])
            if len(self._header) <= 4 + size:
                return b""
            self._decompressor = lzma.LZMADecompressor(
                lzma.FORMAT_RAW,
                filters=[lzma1_properties(self._header[4 : 4 + size])],
            )
            data = self._header[4 + size :]
            self._header = b""
        result = self._decompressor.decompress(data, max_length)
        self._eof = self._decompressor.eof
        return result


def _decompressor(compress_type: int) -> _Decompressor | None:
    """The bzip2 or LZMA decompressor; stored and deflated data need none."""
    if compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
        return None
    if compress_type == zipfile.ZIP_BZIP2:
        return bz2.BZ2Decompressor()
    if compress_type == zipfile.ZIP_LZMA:
        return _LzmaDecompressor()
    raise NotImplementedError("That compression method is not supported")


class ZipMemberReader(io.BufferedIOBase):
    """A readable, seekable stream of one member's uncompressed data.

    ``source`` is positioned at the member's compressed data and is closed
    with the stream.
    """

    def __init__(self, source: io.BytesIO, info: zipfile.ZipInfo) -> None:
        self._compress_type = info.compress_type
        self._source = source
        self._start = source.tell()
        self._compress_size = info.compress_size
        self._file_size = info.file_size
        self._crc = info.CRC
        self.name = info.filename
        self.mode = "rb"
        self._rewind()

    def _rewind(self) -> None:
        self._source.seek(self._start)
        self._compress_left = self._compress_size
        self._left = self._file_size
        self._expected_crc: int | None = self._crc
        self._running_crc = zlib.crc32(b"")
        self._buffer = b""
        self._offset = 0
        self._eof = False
        self._other = _decompressor(self._compress_type)
        self._inflater = (
            zlib.decompressobj(-15)
            if self._compress_type == zipfile.ZIP_DEFLATED
            else None
        )

    def readable(self) -> bool:
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        return True

    def seekable(self) -> bool:
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        return True

    def close(self) -> None:
        try:
            self._source.close()
        finally:
            super().close()

    def peek(self, size: int = 1) -> bytes:
        """Buffered bytes, without moving the position."""
        if size > len(self._buffer) - self._offset:
            chunk = self.read(size)
            if len(chunk) > self._offset:
                self._buffer = chunk + self._buffer[self._offset :]
                self._offset = 0
            else:
                self._offset -= len(chunk)
        return self._buffer[self._offset : self._offset + 512]

    def read(self, size: int | None = -1) -> bytes:
        if self.closed:
            raise ValueError("read from closed file.")
        if size is None or size < 0:
            data = self._buffer[self._offset :]
            self._buffer = b""
            self._offset = 0
            while not self._eof:
                data += self._chunk(_MAX_N)
            return data
        end = size + self._offset
        if end < len(self._buffer):
            data = self._buffer[self._offset : end]
            self._offset = end
            return data
        size = end - len(self._buffer)
        data = self._buffer[self._offset :]
        self._buffer = b""
        self._offset = 0
        while size > 0 and not self._eof:
            chunk = self._chunk(size)
            if size < len(chunk):
                self._buffer = chunk
                self._offset = size
                data += chunk[:size]
                break
            data += chunk
            size -= len(chunk)
        return data

    def read1(self, size: int = -1) -> bytes:
        """Read with at most one decompression step."""
        if self.closed:
            raise ValueError("read from closed file.")
        if size is None or size < 0:
            data = self._buffer[self._offset :]
            self._buffer = b""
            self._offset = 0
            while not self._eof:
                chunk = self._chunk(_MAX_N)
                if chunk:
                    data += chunk
                    break
            return data
        end = size + self._offset
        if end < len(self._buffer):
            data = self._buffer[self._offset : end]
            self._offset = end
            return data
        size = end - len(self._buffer)
        data = self._buffer[self._offset :]
        self._buffer = b""
        self._offset = 0
        while size > 0 and not self._eof:
            chunk = self._chunk(size)
            if size < len(chunk):
                self._buffer = chunk
                self._offset = size
                data += chunk[:size]
                break
            if chunk:
                data += chunk
                break
        return data

    def _compressed(self, size: int) -> bytes:
        if self._compress_left <= 0:
            return b""
        size = min(max(size, _MIN_READ_SIZE), self._compress_left)
        data = self._source.read(size)
        self._compress_left -= len(data)
        if not data:
            raise EOFError
        return data

    def _chunk(self, size: int) -> bytes:
        """Up to ``size`` bytes from one read of compressed data."""
        if self._eof or size <= 0:
            return b""
        if self._inflater is not None:
            data = self._inflater.unconsumed_tail
            if size > len(data):
                data += self._compressed(size - len(data))
            data = self._inflater.decompress(data, max(size, _MIN_READ_SIZE))
            self._eof = self._inflater.eof or (
                self._compress_left <= 0 and not self._inflater.unconsumed_tail
            )
            if self._eof:
                data += self._inflater.flush()
        elif self._other is not None:
            data = self._compressed(size) if self._other.needs_input else b""
            data = self._other.decompress(data, max(size, _MIN_READ_SIZE))
            self._eof = self._other.eof or (
                self._compress_left <= 0 and self._other.needs_input
            )
        else:
            data = self._compressed(size)
            self._eof = self._compress_left <= 0
        data = data[: self._left]
        self._left -= len(data)
        if self._left <= 0:
            self._eof = True
        if self._expected_crc is not None:
            self._running_crc = zlib.crc32(data, self._running_crc)
            if self._eof and self._running_crc != self._expected_crc:
                raise zipfile.BadZipFile(f"Bad CRC-32 for file {self.name!r}")
        return data

    def tell(self) -> int:
        if self.closed:
            raise ValueError("tell on closed file.")
        return self._file_size - self._left - len(self._buffer) + self._offset

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if self.closed:
            raise ValueError("seek on closed file.")
        current = self.tell()
        if whence == os.SEEK_SET:
            target = offset
        elif whence == os.SEEK_CUR:
            target = current + offset
        elif whence == os.SEEK_END:
            target = self._file_size + offset
        else:
            raise ValueError(
                "whence must be os.SEEK_SET (0), os.SEEK_CUR (1), or os.SEEK_END (2)"
            )
        target = max(min(target, self._file_size), 0)
        skip = target - current
        buffered = skip + self._offset
        if 0 <= buffered < len(self._buffer):
            self._offset = buffered
            skip = 0
        elif self._compress_type == zipfile.ZIP_STORED and skip != 0:
            # A CRC cannot cover data that a seek skipped.
            self._expected_crc = None
            skip -= len(self._buffer) - self._offset
            self._source.seek(self._source.tell() + skip)
            self._left -= skip
            self._compress_left -= skip
            self._eof = self._left <= 0
            skip = 0
            self._buffer = b""
            self._offset = 0
        elif skip < 0:
            self._rewind()
            skip = target
        while skip > 0:
            step = min(_MAX_SEEK_READ, skip)
            self.read(step)
            skip -= step
        return self.tell()
