"""SpooledZipWriter writes zipfile's bytes without keeping entries in memory."""

import gc
import io
import sqlite3
import struct
import sys
import tempfile
import time
import tracemalloc
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import IO
from unittest.mock import MagicMock

import pytest

from onyx.file_processing.zip_writer import SpooledZipWriter

_EXTRA_ID = 0xCAFE
Writer = zipfile.ZipFile | SpooledZipWriter
Write = Callable[[Writer], None]


def _zipfile(output: IO[bytes]) -> zipfile.ZipFile:
    return zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED)


def _outcome(write: Write, writer: Callable[[io.BytesIO], Writer]) -> object:
    output = io.BytesIO()
    try:
        with writer(output) as archive:
            write(archive)
    except Exception as exc:  # noqa: BLE001
        return (type(exc), str(exc), output.getvalue())
    return output.getvalue()


def _assert_same_bytes(write: Write) -> None:
    ours = _outcome(write, SpooledZipWriter)
    assert ours == _outcome(write, _zipfile)
    if isinstance(ours, bytes):
        with zipfile.ZipFile(io.BytesIO(ours)) as archive:
            assert archive.testzip() is None


@pytest.mark.parametrize(
    "compression",
    [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA],
)
def test_spooled_writer_writes_the_same_bytes_as_zipfile(compression: int) -> None:
    def write(archive: Writer) -> None:
        for index in range(0x10001):
            info = zipfile.ZipInfo(f"{index:x}", (2022, 2, 2, 2, 2, 2))
            info.compress_type = compression
            info.extra = struct.pack("<HH", _EXTRA_ID, 1) + b"e"
            info.comment = b"note" if index % 7 else b""
            archive.writestr(info, b"data" if index % 3 else b"")

    if compression in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
        # Fewer entries keep these slower compressors quick; ZIP64 is covered above.
        def write_some(archive: Writer) -> None:
            for index in range(300):
                info = zipfile.ZipInfo(f"{index:x}", (2022, 2, 2, 2, 2, 2))
                info.compress_type = compression
                info.compress_level = 1 if index % 2 else None
                archive.writestr(info, b"data %d " % index * index)

        _assert_same_bytes(write_some)
        return
    _assert_same_bytes(write)
    ours = _outcome(write, SpooledZipWriter)
    assert isinstance(ours, bytes) and b"PK\x06\x06" in ours[-200:]


def test_entry_fields_and_streams_match_zipfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(time, "time", lambda: 1_700_000_000.0)

    def write(archive: Writer) -> None:
        archive.writestr("folder/", b"")
        archive.writestr("text.txt", "unicode text é")
        archive.writestr("été 中.md", b"names outside ASCII")
        level = zipfile.ZipInfo("level", (2030, 12, 31, 23, 59, 58))
        level.compress_type = zipfile.ZIP_DEFLATED
        level.compress_level = 9
        level.create_system = 0
        level.external_attr = 0o755 << 16
        level.internal_attr = 1
        archive.writestr(level, b"z" * 5000)
        stream = zipfile.ZipInfo("streamed", (2024, 5, 6, 7, 8, 10))
        stream.compress_type = zipfile.ZIP_DEFLATED
        with archive.open(stream, mode="w") as member:
            member.write(b"first ")
            member.write(bytearray(b"second "))
            member.write(memoryview(b"third"))

    _assert_same_bytes(write)


@pytest.mark.parametrize("declared_size", [(1 << 31) - 1, 1 << 31, 1 << 32])
@pytest.mark.parametrize(
    "compression",
    [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA],
)
def test_small_stream_with_zip64_size_hint_matches_zipfile(
    declared_size: int, compression: int
) -> None:
    def write(archive: Writer) -> None:
        info = zipfile.ZipInfo("SKILL.md", (2024, 1, 1, 0, 0, 0))
        info.file_size = declared_size
        info.compress_type = compression
        with archive.open(info, mode="w") as member:
            member.write(b"small member despite the size hint")

    _assert_same_bytes(write)


def test_written_entries_change_as_in_zipfile() -> None:
    def fields(writer: Callable[[io.BytesIO], Writer]) -> list[tuple[object, ...]]:
        infos = [zipfile.ZipInfo(name) for name in ("a", "é", "lz")]
        infos[2].compress_type = zipfile.ZIP_LZMA
        with writer(io.BytesIO()) as archive:
            for info in infos:
                archive.writestr(info, b"content")
        return [
            (
                info.header_offset,
                info.compress_size,
                info.file_size,
                info.CRC,
                info.external_attr,
                info.extract_version,
                info.create_version,
                # Python 3.13.0 leaves the UTF-8 name flag out; 3.13.16 sets it.
                info.flag_bits | (0x800 if sys.version_info < (3, 13, 16) else 0),
            )
            for info in infos
        ]

    assert fields(SpooledZipWriter) == fields(_zipfile)


def _misuse_open_twice(archive: Writer) -> None:
    first = archive.open(zipfile.ZipInfo("a"), mode="w")
    try:
        archive.open(zipfile.ZipInfo("b"), mode="w")
    finally:
        first.close()


def _misuse_writestr_while_open(archive: Writer) -> None:
    first = archive.open(zipfile.ZipInfo("a"), mode="w")
    try:
        archive.writestr("b", b"")
    finally:
        first.close()


def _misuse_unsupported_compression(archive: Writer) -> None:
    archive.writestr("a", b"kept")
    info = zipfile.ZipInfo("b")
    info.compress_type = 99
    archive.writestr(info, b"data")


@pytest.mark.parametrize(
    "write",
    [
        _misuse_open_twice,
        _misuse_writestr_while_open,
        _misuse_unsupported_compression,
    ],
)
def test_misuse_fails_as_in_zipfile(write: Write) -> None:
    _assert_same_bytes(write)


def test_closed_writer_refuses_writes_as_zipfile_does() -> None:
    for writer in (SpooledZipWriter, _zipfile):
        archive = writer(io.BytesIO())
        archive.close()
        archive.close()
        with pytest.raises(ValueError, match="already closed"):
            archive.writestr("a", b"")
        with pytest.raises(ValueError, match="already closed"):
            archive.open(zipfile.ZipInfo("a"), mode="w")


def test_offsets_past_four_gib_use_zip64_records_as_in_zipfile(tmp_path: Path) -> None:
    start = 5 << 30

    def write(path: Path, writer: Callable[[io.BufferedRandom], Writer]) -> bytes:
        with path.open("w+b") as output:
            output.seek(start)
            with writer(output) as archive:
                info = zipfile.ZipInfo("big offset", (2024, 1, 1, 0, 0, 0))
                info.extra = (
                    struct.pack("<HHQ", 1, 8, 7)
                    + struct.pack("<HH", _EXTRA_ID, 2)
                    + b"ok"
                    + b"\x01"
                )
                archive.writestr(info, b"data")
            output.seek(start)
            return output.read()

    ours = write(tmp_path / "ours.zip", SpooledZipWriter)
    assert ours == write(tmp_path / "zipfile.zip", _zipfile)
    assert b"PK\x06\x06" in ours


def test_writer_needs_a_seekable_output() -> None:
    output = MagicMock(spec=io.RawIOBase)
    output.seekable.return_value = False
    with pytest.raises(ValueError, match="seekable"):
        SpooledZipWriter(output)


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


def test_writer_closes_sqlite_when_member_metadata_exceeds_disk_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = sqlite3.connect("")
    monkeypatch.setattr(sqlite3, "connect", lambda _: connection)
    writer = SpooledZipWriter(io.BytesIO())
    pages = connection.execute("PRAGMA page_count").fetchone()[0]
    connection.execute(f"PRAGMA max_page_count={pages}")
    try:
        with pytest.raises(sqlite3.OperationalError, match="database or disk is full"):
            with writer:
                writer.writestr(zipfile.ZipInfo("a" * 8192), b"data")
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
        writer.close()
    finally:
        connection.close()


def _peak(call: Callable[[], object]) -> int:
    tracemalloc.start()
    try:
        call()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_writer_memory_does_not_grow_with_entries() -> None:
    def write(writer: Callable[[IO[bytes]], Writer], count: int) -> None:
        # A disk file keeps the output itself out of the measurement.
        with tempfile.TemporaryFile() as output, writer(output) as archive:
            for index in range(count):
                info = zipfile.ZipInfo(f"{index:x}", (2022, 2, 2, 2, 2, 2))
                archive.writestr(info, b"")

    small = _peak(lambda: write(SpooledZipWriter, 10_000))
    large = _peak(lambda: write(SpooledZipWriter, 80_000))
    zipfile_large = _peak(lambda: write(_zipfile, 80_000))
    assert large < 2 * small < 512 * 1024 < zipfile_large // 40


def test_failed_member_open_has_no_deferred_write_or_unraisable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unraisable = MagicMock()
    monkeypatch.setattr(sys, "unraisablehook", unraisable)
    for writer in (SpooledZipWriter, _zipfile):
        output = io.BytesIO()
        with writer(output) as archive:
            info = zipfile.ZipInfo("invalid-extra")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.extra = bytes(70_000)
            with pytest.raises(struct.error):
                archive.open(info, mode="w")
            gc.collect()
            assert output.getvalue() == b""
            unraisable.assert_not_called()
            archive.writestr("valid.txt", b"kept")
        with zipfile.ZipFile(io.BytesIO(output.getvalue())) as result:
            assert result.namelist() == ["valid.txt"]
            assert result.read("valid.txt") == b"kept"


def test_string_name_uses_sanitized_directory_attributes() -> None:
    def write(archive: Writer) -> None:
        archive.writestr("a/\0b", b"")

    _assert_same_bytes(write)
