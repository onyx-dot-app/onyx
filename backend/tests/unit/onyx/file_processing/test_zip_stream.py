"""ZipIndex member streams read, seek and fail as zipfile's member streams do."""

import io
import os
import random
import struct
import sys
import zipfile
from collections.abc import Callable

import pytest

from onyx.file_processing.zip_index import ZipIndex

# Older zipfile releases (3.13.0 among them) decompress bzip2 and LZMA without
# a bound and keep a stale compressed size after a stored seek. ZipIndex streams
# follow 3.13.16, so seeks and the read that reports a CRC error can differ there.
_BOUNDED_ZIPFILE = sys.version_info >= (3, 13, 16)

_COMPRESSIONS = {
    "stored": zipfile.ZIP_STORED,
    "deflated": zipfile.ZIP_DEFLATED,
    "bzip2": zipfile.ZIP_BZIP2,
    "lzma": zipfile.ZIP_LZMA,
}


def _content() -> bytes:
    rng = random.Random(3)
    lines = b"".join(b"line %d of the member\n" % index for index in range(4000))
    return lines + rng.randbytes(70_000) + lines


def _archive(compression: int) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression) as archive:
        archive.writestr("member", _content())
        archive.writestr("empty", b"")
    return output.getvalue()


def test_closed_index_releases_archive_bytes() -> None:
    data = _archive(zipfile.ZIP_STORED)
    references = sys.getrefcount(data)
    index = ZipIndex(data)
    assert index.read("member") == _content()
    index.close()
    index.close()
    assert sys.getrefcount(data) == references


@pytest.mark.parametrize("compression", _COMPRESSIONS.values())
@pytest.mark.parametrize("size", [-1, 0, 5])
@pytest.mark.parametrize("buffered", [False, True])
def test_read1_refuses_closed_stream(
    compression: int, size: int, buffered: bool
) -> None:
    with ZipIndex(_archive(compression)) as index:
        stream = index.open(index.getinfo("member"))
        if buffered:
            assert stream.read(1) == _content()[:1]
        stream.close()
        with pytest.raises(ValueError, match="read from closed file"):
            stream.read1(size)


Step = Callable[[io.BufferedIOBase], object]

_STEPS: list[Step] = [
    lambda s: s.read(0),
    lambda s: s.read(1),
    lambda s: s.read(7),
    lambda s: s.read1(5),
    lambda s: s.peek(3),  # ty: ignore[unresolved-attribute]
    lambda s: s.readline(),
    lambda s: s.tell(),
    lambda s: s.seek(0),
    lambda s: s.read(100),
    lambda s: s.seek(-5, os.SEEK_END),
    lambda s: s.read(),
    lambda s: s.seek(3, os.SEEK_CUR),
    lambda s: s.seek(-200_000, os.SEEK_CUR),
    lambda s: s.read(4096 * 3 + 1),
    lambda s: s.seek(150_000),
    lambda s: s.read1(-1),
    lambda s: s.seek(10**9),
    lambda s: s.read(),
    lambda s: s.seek(1, 3),
    lambda s: s.seek(20),
    lambda s: s.read1(10**6),
    lambda s: s.readlines(2),
    lambda s: (s.seekable(), s.readable()),
    lambda s: s.read(-1),
]


def _run(stream: io.BufferedIOBase, steps: list[Step]) -> list[object]:
    results: list[object] = []
    for step in steps:
        try:
            results.append(step(stream))
        except Exception as exc:  # noqa: BLE001
            results.append((type(exc), str(exc)))
    stream.close()
    for after_close in (
        lambda: stream.read(),
        lambda: stream.tell(),
        lambda: stream.seek(0),
    ):
        try:
            results.append(after_close())
        except ValueError as exc:
            results.append(str(exc))
    return results


def _both(data: bytes, name: str, steps: list[Step]) -> tuple[object, object]:
    def native() -> object:
        with zipfile.ZipFile(io.BytesIO(data)) as reference:
            stream = reference.open(name)
            assert isinstance(stream, io.BufferedIOBase)
            return _run(stream, steps)

    def indexed() -> object:
        with ZipIndex(data) as index:
            return _run(index.open(index.getinfo(name)), steps)

    def guarded(call: Callable[[], object]) -> object:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            return (type(exc), str(exc))

    return guarded(indexed), guarded(native)


@pytest.mark.parametrize("compression", _COMPRESSIONS)
@pytest.mark.parametrize("name", ["member", "empty"])
def test_stream_steps_match_zipfile(compression: str, name: str) -> None:
    if not _BOUNDED_ZIPFILE and compression in ("bzip2", "lzma"):
        pytest.skip("This zipfile reads bzip2 and LZMA without a bound")
    ours, expected = _both(_archive(_COMPRESSIONS[compression]), name, _STEPS)
    assert ours == expected


def test_streams_name_the_member_and_open_in_binary_mode() -> None:
    data = _archive(zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(io.BytesIO(data)) as reference, ZipIndex(data) as index:
        with (
            reference.open("member") as expected,
            index.open(index.getinfo("member")) as ours,
        ):
            assert (
                (ours.mode, ours.name)
                == (expected.mode, expected.name)
                == ("rb", "member")
            )


@pytest.mark.parametrize("compression", _COMPRESSIONS)
@pytest.mark.parametrize("size", [1, 4096, 65536])
def test_chunked_reads_match_zipfile(compression: str, size: int) -> None:
    def chunks(stream: io.BufferedIOBase) -> list[bytes]:
        found = []
        while chunk := stream.read(size):
            found.append(chunk)
        return found

    data = _archive(_COMPRESSIONS[compression])
    ours, expected = _both(data, "member", [chunks])
    assert ours == expected


def _corrupt(compression: int, change: str) -> bytes:
    data = bytearray(_archive(compression))
    record = data.index(b"PK\x01\x02")
    start = 30 + len(b"member")
    if change == "crc":
        for offset in (14, record + 16):
            data[offset] ^= 1
    elif change == "data":
        data[start + 40] ^= 0xFF
    elif change == "short data":
        for offset in (18, record + 20):
            size = struct.unpack_from("<L", data, offset)[0]
            struct.pack_into("<L", data, offset, size // 2)
    elif change == "long data":
        for offset in (18, record + 20):
            size = struct.unpack_from("<L", data, offset)[0]
            struct.pack_into("<L", data, offset, size + 10)
    elif change == "large file size":
        for offset in (22, record + 24):
            struct.pack_into("<L", data, offset, 10**7)
    return bytes(data)


@pytest.mark.parametrize("compression", _COMPRESSIONS)
@pytest.mark.parametrize(
    "change", ["crc", "data", "short data", "long data", "large file size"]
)
def test_corrupt_member_data_fails_as_in_zipfile(compression: str, change: str) -> None:
    data = _corrupt(_COMPRESSIONS[compression], change)
    chunks: list[Step] = [lambda s: s.read(4096)] * 60
    for steps in [[lambda s: s.read()]] + (
        [chunks, _STEPS] if _BOUNDED_ZIPFILE else []
    ):
        ours, expected = _both(data, "member", steps)
        assert ours == expected


def _lzma_member(header: bytes) -> bytes:
    data = bytearray(_archive(zipfile.ZIP_LZMA))
    start = 30 + len(b"member")
    data[start : start + len(header)] = header
    return bytes(data)


@pytest.mark.parametrize(
    "header",
    [
        b"\x09\x04\x05\x00\x5e\x00\x00\x80\x00",
        b"\x09\x04\x05\x00\xe1\x00\x00\x80\x00",
        b"\x09\x04\x05\x00\x25\x00\x10\x00\x00",
        b"\x09\x04\x04\x00\x5d\x00\x00\x80\x00",
        b"\x09\x04\xff\xff",
    ],
)
def test_lzma_properties_fail_as_in_zipfile(header: bytes) -> None:
    ours, expected = _both(_lzma_member(header), "member", [lambda s: s.read()])
    assert ours == expected


def test_every_lzma_property_byte_fails_or_reads_as_in_zipfile() -> None:
    for value in range(256):
        header = b"\x09\x04\x05\x00" + bytes([value]) + (1 << 23).to_bytes(4, "little")
        ours, expected = _both(_lzma_member(header), "member", [lambda s: s.read()])
        assert ours == expected, value
