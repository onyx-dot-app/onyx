"""ZipIndex reads the entries zipfile reads, without holding them in memory."""

import io
import sqlite3
import struct
import subprocess
import sys
import tracemalloc
import warnings
import zipfile
import zlib
from collections.abc import Callable
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from onyx.file_processing.zip_index import SpooledZipWriter, ZipIndex
from onyx.file_processing.zip_limits import ZipMetadataLimitError

_EXTRA_ID = 0xCAFE


def raw_zip(
    entries: list[tuple[str, bytes]],
    *,
    extra_bytes: int = 0,
    comment_bytes: int = 0,
    zip64: bool = False,
    shared_header: bool = False,
) -> bytes:
    """Write a ZIP with struct, so a test controls each central directory field."""
    extra = struct.pack("<HH", _EXTRA_ID, extra_bytes) + bytes(extra_bytes)
    extra = extra if extra_bytes else b""
    comment = b"c" * comment_bytes
    local = io.BytesIO()
    central = io.BytesIO()
    for name, data in entries:
        encoded = name.encode()
        crc = zlib.crc32(data)
        offset = 0 if shared_header and local.tell() else local.tell()
        if not (shared_header and offset == 0 and local.tell()):
            local.write(
                struct.pack(
                    "<4s5H3L2H",
                    b"PK\x03\x04",
                    20,
                    0x800,
                    0,
                    0,
                    0,
                    crc,
                    len(data),
                    len(data),
                    len(encoded),
                    0,
                )
                + encoded
                + data
            )
        central.write(
            struct.pack(
                "<4s6H3L5H2L",
                b"PK\x01\x02",
                20,
                20,
                0x800,
                0,
                0,
                0,
                crc,
                len(data),
                len(data),
                len(encoded),
                len(extra),
                len(comment),
                0,
                0,
                0,
                offset,
            )
            + encoded
            + extra
            + comment
        )
    body = local.getvalue() + central.getvalue()
    count = len(entries)
    size = central.tell()
    start = local.tell()
    if not zip64:
        return body + struct.pack(
            "<4s4H2LH",
            b"PK\x05\x06",
            0,
            0,
            min(count, 0xFFFF),
            min(count, 0xFFFF),
            size,
            start,
            0,
        )
    return with_zip64_end(body, count, size, start)


def with_zip64_end(body: bytes, count: int, size: int, start: int) -> bytes:
    record = struct.pack(
        "<4sQ2H2L4Q", b"PK\x06\x06", 44, 45, 45, 0, 0, count, count, size, start
    )
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, len(body), 1)
    end = struct.pack(
        "<4s4H2LH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0
    )
    return body + record + locator + end


def directory_size(data: bytes) -> int:
    return int.from_bytes(data[-10:-6], "little")


def _written() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in [("b.txt", b"b" * 900), ("a/", b""), ("a/z.txt", b"z")]:
            info = zipfile.ZipInfo(name, (2020, 1, 2, 3, 4, 6))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
        archive.comment = b"archive comment"
    return output.getvalue()


def _unicode_extra() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("plain.txt")
        unicode_name = "ünïcode.txt".encode()
        info.extra = (
            struct.pack(
                "<HHBL", 0x7075, 5 + len(unicode_name), 1, zlib.crc32(b"plain.txt")
            )
            + unicode_name
        )
        archive.writestr(info, b"u")
    return output.getvalue()


_PARITY: dict[str, Callable[[], bytes]] = {
    "deflated with comment": _written,
    "prepended bytes": lambda: b"prefix" + _written(),
    "duplicate names": lambda: raw_zip([("b", b"1"), ("a", b"2"), ("b", b"3")]),
    "folders, extras and comments": lambda: raw_zip(
        [("d/", b""), ("d/x", b"x"), ("c", b"")], extra_bytes=300, comment_bytes=70
    ),
    "zip64 end record": lambda: raw_zip([("z", b"1"), ("y", b"22")], zip64=True),
    "unicode path extra": _unicode_extra,
    "shared header offset": lambda: raw_zip(
        [("same", b""), ("same", b"")], shared_header=True
    ),
}


def _fields(info: zipfile.ZipInfo) -> tuple[object, ...]:
    return (
        info.filename,
        info.orig_filename,
        info.header_offset,
        info.compress_size,
        info.file_size,
        info.CRC,
        info.date_time,
        info.extra,
        info.comment,
        info.flag_bits,
        info.external_attr,
        info.create_system,
        info.is_dir(),
        info._end_offset,  # ty: ignore[unresolved-attribute]
    )


def _read(open_member: Callable[[], object]) -> object:
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        try:
            return open_member()
        except Exception as exc:  # noqa: BLE001
            return (type(exc), str(exc))


def _index_reader(index: ZipIndex) -> Callable[[zipfile.ZipInfo], bytes]:
    def read(info: zipfile.ZipInfo) -> bytes:
        with index.open(info) as source:
            return source.read()

    return read


def _member(read: Callable[[zipfile.ZipInfo], bytes], info: zipfile.ZipInfo) -> object:
    return _read(partial(read, info))


@pytest.mark.parametrize("fixture", _PARITY)
def test_entries_match_zipfile(fixture: str) -> None:
    data = _PARITY[fixture]()
    with zipfile.ZipFile(io.BytesIO(data)) as reference, ZipIndex(data) as index:
        expected = reference.infolist()
        assert [_fields(info) for info in index.infos()] == [
            _fields(info) for info in expected
        ]
        assert [_fields(info) for info in index.sorted_infos()] == [
            _fields(info) for info in sorted(expected, key=lambda i: i.filename)
        ]
        for info, ours in zip(expected, index.infos(), strict=True):
            assert _member(_index_reader(index), ours) == _member(reference.read, info)
            assert _fields(index.getinfo(info.filename)) == _fields(
                reference.getinfo(info.filename)
            )
            assert _read(partial(index.read, info.filename)) == _read(
                partial(reference.read, info.filename)
            )
        with pytest.raises(KeyError):
            index.getinfo("missing")


@pytest.mark.parametrize("zip64", [False, True])
@pytest.mark.parametrize("legacy_location", [False, True])
@pytest.mark.parametrize("prefix", [b"", b"prepended data"])
@pytest.mark.parametrize("comment", [b"", b"archive comment"])
def test_zip64_end_locations_across_python_releases(
    monkeypatch: pytest.MonkeyPatch,
    zip64: bool,
    legacy_location: bool,
    prefix: bytes,
    comment: bytes,
) -> None:
    data = prefix + raw_zip([("SKILL.md", b"saved skill")], zip64=zip64)
    data = data[:-2] + struct.pack("<H", len(comment)) + comment
    with zipfile.ZipFile(io.BytesIO(data)) as reference:
        expected = [_fields(info) for info in reference.infolist()]
    end = zipfile._EndRecData(io.BytesIO(data))  # ty: ignore[unresolved-attribute]
    assert end is not None
    # Python 3.13.0 returns the ordinary end position even for ZIP64.
    end[9] = data.index(
        b"PK\x06\x06" if zip64 and not legacy_location else b"PK\x05\x06"
    )
    monkeypatch.setattr(zipfile, "_EndRecData", lambda _: end)
    with ZipIndex(data) as index:
        assert [_fields(info) for info in index.infos()] == expected
        assert index.read("SKILL.md") == b"saved skill"


@pytest.mark.parametrize("failure", ["connect", "schema"])
def test_reader_closes_archive_when_storage_creation_fails(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    data = raw_zip([("SKILL.md", b"body")])
    connection = sqlite3.connect("")
    failed = MagicMock(wraps=connection)
    error = sqlite3.OperationalError("storage failure")
    if failure == "connect":
        monkeypatch.setattr(sqlite3, "connect", MagicMock(side_effect=error))
    else:
        failed.executescript.side_effect = error
        monkeypatch.setattr(sqlite3, "connect", lambda _: failed)
    closed: list[zipfile.ZipFile] = []
    original_close = zipfile.ZipFile.close

    def close(archive: zipfile.ZipFile) -> None:
        # ZipFile.__del__ also calls close; count only closes of open archives.
        was_open = archive.fp is not None
        original_close(archive)
        if was_open:
            closed.append(archive)

    monkeypatch.setattr(zipfile.ZipFile, "close", close)
    try:
        with pytest.raises(sqlite3.OperationalError, match="storage failure") as caught:
            ZipIndex(data)
        assert caught.value is error
        assert len(closed) == 1
        with pytest.raises(ValueError, match="closed"):
            closed[0].open("SKILL.md")
        if failure == "schema":
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
    finally:
        connection.close()


def test_writer_closes_sqlite_when_schema_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect("")
    failed = MagicMock(wraps=connection)
    failed.execute.side_effect = sqlite3.OperationalError("schema failure")
    monkeypatch.setattr(sqlite3, "connect", lambda _: failed)
    try:
        with pytest.raises(sqlite3.OperationalError, match="schema failure"):
            SpooledZipWriter(io.BytesIO())
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    finally:
        connection.close()


def _with_version(data: bytes, version: int) -> bytes:
    start = data.index(b"PK\x01\x02")
    return data[: start + 6] + bytes([version, 0]) + data[start + 8 :]


_MALFORMED: dict[str, Callable[[], bytes]] = {
    "not a zip": lambda: b"not a zip",
    "truncated directory": lambda: (
        raw_zip([("a", b"1")])[:-22]
        + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, 200, 0, 0)
    ),
    "bad directory magic": lambda: raw_zip([("a", b"1")]).replace(
        b"PK\x01\x02", b"PK\x01\x09"
    ),
    "corrupt zip64 end": lambda: with_zip64_end(
        raw_zip([("a", b"1")])[:-22], 1, 1 << 40, 0
    ),
    "bad offset": lambda: (
        raw_zip([("a", b"1")])[:-22]
        + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, 1 << 20, 0, 0)
    ),
    "corrupt extra field": lambda: raw_zip([("a", b"1")], extra_bytes=8).replace(
        struct.pack("<HH", _EXTRA_ID, 8), struct.pack("<HH", _EXTRA_ID, 90)
    ),
    "unsupported version": lambda: _with_version(raw_zip([("a", b"1")]), 64),
    "forged entry count": lambda: (
        raw_zip([("a", b"1")])[:-14]
        + struct.pack("<2H", 0xFFFF, 0xFFFF)
        + raw_zip([("a", b"1")])[-10:]
    ),
}


@pytest.mark.parametrize("fixture", _MALFORMED)
def test_malformed_archives_fail_as_in_zipfile(fixture: str) -> None:
    data = _MALFORMED[fixture]()

    def entries(archive: Callable[[], object]) -> object:
        return _read(archive)

    expected = entries(
        lambda: [_fields(i) for i in zipfile.ZipFile(io.BytesIO(data)).infolist()]
    )

    def ours() -> list[tuple[object, ...]]:
        with ZipIndex(data) as index:
            return [_fields(info) for info in index.infos()]

    assert entries(ours) == expected


def test_overlapped_entries_fail_as_in_zipfile() -> None:
    data = bytearray(raw_zip([("a", b"1" * 50), ("b", b"2")]))
    # Point the second entry into the first entry's data.
    second = data.rindex(b"PK\x01\x02")
    data[second + 42 : second + 46] = struct.pack("<L", 10)
    data = bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as reference, ZipIndex(data) as index:
        for info, ours in zip(reference.infolist(), index.infos(), strict=True):
            assert _member(_index_reader(index), ours) == _member(reference.read, info)
        with pytest.raises(zipfile.BadZipFile, match="Overlapped entries"):
            reference.read("a")


@pytest.mark.parametrize("offset", [2**63 - 1, 2**63, 2**64 - 1])
def test_header_offsets_past_sqlite_integers_fail_as_in_zipfile(offset: int) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("a")
        info.extra = struct.pack("<HHQ", 1, 8, offset)
        archive.writestr(info, b"x")
    data = bytearray(output.getvalue())
    record = data.index(b"PK\x01\x02")
    data[record + 42 : record + 46] = struct.pack("<L", 0xFFFFFFFF)
    data = bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as reference, ZipIndex(data) as index:
        for info, ours in zip(reference.infolist(), index.infos(), strict=True):
            assert _fields(ours) == _fields(info)
            assert _member(_index_reader(index), ours) == _member(reference.read, info)


def test_metadata_cap_refuses_before_any_entry_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = raw_zip([(f"{index}/", b"") for index in range(1000)])
    created: list[str] = []

    class CountingZipInfo(zipfile.ZipInfo):
        __slots__ = ()

        def __init__(
            self,
            filename: str = "NoName",
            date_time: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0),
        ) -> None:
            super().__init__(filename, date_time)
            created.append(filename)

    monkeypatch.setattr(zipfile, "ZipInfo", CountingZipInfo)
    with pytest.raises(ZipMetadataLimitError):
        ZipIndex(data, max_metadata_bytes=directory_size(data) - 1)
    assert created == []
    with ZipIndex(data, max_metadata_bytes=directory_size(data)) as index:
        assert sum(1 for _ in index.infos()) == 1000


def _peak(call: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        call()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_reader_memory_does_not_grow_with_entries() -> None:
    def read_all(data: bytes) -> None:
        with ZipIndex(data) as index:
            for info in index.sorted_infos():
                with index.open(info) as source:
                    source.read()

    small = raw_zip([(f"{index:x}", b"") for index in range(10_000)])
    large = raw_zip([(f"{index:x}", b"") for index in range(80_000)], zip64=True)
    zipfile_peak = _peak(lambda: zipfile.ZipFile(io.BytesIO(large)).infolist())

    assert _peak(lambda: read_all(large)) < 512 * 1024 < zipfile_peak // 40
    assert _peak(lambda: read_all(large)) < 2 * _peak(lambda: read_all(small))


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_spooled_writer_writes_the_same_bytes_as_zipfile(compression: int) -> None:
    def write(archive: zipfile.ZipFile | SpooledZipWriter) -> None:
        with archive:
            for index in range(0x10001):
                info = zipfile.ZipInfo(f"{index:x}", (2022, 2, 2, 2, 2, 2))
                info.compress_type = compression
                info.extra = struct.pack("<HH", _EXTRA_ID, 1) + b"e"
                info.comment = b"note" if index % 7 else b""
                archive.writestr(info, b"data" if index % 3 else b"")

    expected = io.BytesIO()
    write(zipfile.ZipFile(expected, "w", compression=zipfile.ZIP_DEFLATED))
    ours = io.BytesIO()
    write(SpooledZipWriter(ours))

    assert ours.getvalue() == expected.getvalue()
    assert b"PK\x06\x06" in ours.getvalue()[-200:]


def test_writer_can_finish_after_close_with_an_open_member() -> None:
    output = io.BytesIO()
    writer = SpooledZipWriter(output)
    member = writer.open(zipfile.ZipInfo("SKILL.md"), mode="w")
    try:
        member.write(b"saved skill")
        with pytest.raises(ValueError, match="open writing handle"):
            writer.close()
    finally:
        member.close()
        writer.close()
    writer.close()
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        assert archive.read("SKILL.md") == b"saved skill"


def test_import_does_not_write_a_probe_archive() -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from unittest.mock import patch; "
            "guard = patch('zipfile.ZipFile.writestr', side_effect=RuntimeError('import wrote ZIP')); "
            "guard.start(); import onyx.file_processing.zip_index; guard.stop()",
        ],
        cwd=Path(__file__).resolve().parents[4],
        check=True,
        capture_output=True,
        text=True,
    )
