"""ZipIndex reads the entries zipfile reads, without holding them in memory."""

import io
import random
import sqlite3
import struct
import subprocess
import sys
import threading
import tracemalloc
import warnings
import zipfile
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from onyx.file_processing import zip_index
from onyx.file_processing.zip_index import IndexedZipInfo, ZipIndex
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


def with_zip64_end(
    body: bytes,
    count: int,
    size: int,
    start: int,
    *,
    extensible: bytes = b"",
    record_size: int | None = None,
    locator_offset: int | None = None,
    disks: int = 1,
    signature: bytes = b"PK\x06\x06",
) -> bytes:
    record = struct.pack(
        "<4sQ2H2L4Q",
        signature,
        44 + len(extensible) if record_size is None else record_size,
        45,
        45,
        0,
        0,
        count,
        count,
        size,
        start,
    )
    offset = len(body) if locator_offset is None else locator_offset
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, offset, disks)
    end = struct.pack(
        "<4s4H2LH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0
    )
    return body + record + extensible + locator + end


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
        info.internal_attr,
        info.create_version,
        info.extract_version,
        info.reserved,
        info.volume,
        info.compress_type,
    )


def _read(open_member: Callable[[], object]) -> object:
    """The value or error of a call, with the warnings it gave."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            value = open_member()
        except Exception as exc:  # noqa: BLE001
            value = (type(exc), str(exc))
    return value, [str(warning.message) for warning in caught]


def _index_reader(index: ZipIndex) -> Callable[[IndexedZipInfo], bytes]:
    def read(info: IndexedZipInfo) -> bytes:
        with index.open(info) as source:
            return source.read()

    return read


def _reference_reader(reference: zipfile.ZipFile) -> Callable[[zipfile.ZipInfo], bytes]:
    def read(info: zipfile.ZipInfo) -> bytes:
        with reference.open(info) as source:
            return source.read()

    return read


def _member[Info: zipfile.ZipInfo](read: Callable[[Info], bytes], info: Info) -> object:
    return _read(partial(read, info))


def _outcome(data: bytes, *, indexed: bool) -> object:
    """Everything a caller can see from one archive, errors included."""

    def entries_and_reads() -> object:
        if indexed:
            with ZipIndex(data) as index:
                infos = list(index.infos())
                return (
                    [_fields(info) for info in infos],
                    [_fields(info) for info in index.sorted_infos()],
                    [_member(_index_reader(index), info) for info in infos],
                    [_read(partial(index.read, info.filename)) for info in infos],
                )
        with zipfile.ZipFile(io.BytesIO(data)) as reference:
            expected = reference.infolist()
            ordered = sorted(expected, key=lambda info: info.filename)
            return (
                [_fields(info) for info in expected],
                [_fields(info) for info in ordered],
                [_member(_reference_reader(reference), info) for info in expected],
                [_read(partial(reference.read, info.filename)) for info in expected],
            )

    return _read(entries_and_reads)


@pytest.mark.parametrize("fixture", _PARITY)
def test_entries_match_zipfile(fixture: str) -> None:
    data = _PARITY[fixture]()
    assert _outcome(data, indexed=True) == _outcome(data, indexed=False)
    with zipfile.ZipFile(io.BytesIO(data)) as reference, ZipIndex(data) as index:
        for info in reference.infolist():
            assert _fields(index.getinfo(info.filename)) == _fields(
                reference.getinfo(info.filename)
            )
        with pytest.raises(KeyError):
            index.getinfo("missing")


def test_entries_keep_the_directory_name_that_local_headers_match() -> None:
    with ZipIndex(_unicode_extra()) as index:
        [info] = index.infos()
        assert (info.filename, info.directory_name) == (
            "\u00fcn\u00efcode.txt",
            "plain.txt",
        )
        assert index.read(info.filename) == b"u"


def _zip64(
    *,
    prefix: bytes = b"",
    comment: bytes = b"",
    size_delta: int = 0,
    extensible: bytes = b"",
    record_size: int | None = None,
    locator_offset: int | None = None,
    disks: int = 1,
    signature: bytes = b"PK\x06\x06",
) -> bytes:
    """One saved Skill with ZIP64 end records."""
    plain = raw_zip([("SKILL.md", b"saved skill")])
    body = plain[:-22]
    size = directory_size(plain)
    data = with_zip64_end(
        body,
        1,
        size + size_delta,
        len(body) - size,
        extensible=extensible,
        record_size=record_size,
        locator_offset=locator_offset,
        disks=disks,
        signature=signature,
    )
    return prefix + data[:-2] + struct.pack("<H", len(comment)) + comment


_CHECKED_RECORD = "Corrupt zip64 end of central directory record"
_NOT_FOUND = "Zip64 end of central directory record not found"
_BAD_OFFSET = "Bad offset for central directory"
# The local header offset, or the error, on Python 3.13.16 and on 3.13.0,
# whose zipfile does not check the ZIP64 records (gh-139700).
_ZIP64_ENDS: dict[str, tuple[Callable[[], bytes], int | str, int | str]] = {
    "well formed": (lambda: _zip64(), 0, 0),
    "prepended": (lambda: _zip64(prefix=b"prepended data"), 14, 14),
    "comment": (lambda: _zip64(comment=b"archive comment"), 0, 0),
    "prepended with comment": (
        lambda: _zip64(prefix=b"prepended data", comment=b"archive comment"),
        14,
        14,
    ),
    "extensible data": (lambda: _zip64(extensible=bytes(8)), 0, _BAD_OFFSET),
    "extensible data, prepended": (
        lambda: _zip64(prefix=b"prefix", extensible=bytes(8)),
        _NOT_FOUND,
        _BAD_OFFSET,
    ),
    "wrong record size field": (lambda: _zip64(record_size=45), _CHECKED_RECORD, 0),
    "wrong directory size": (
        lambda: _zip64(size_delta=1),
        _CHECKED_RECORD,
        "Bad magic number for central directory",
    ),
    "locator past record": (
        lambda: _zip64(locator_offset=1 << 20),
        "Corrupt zip64 end of central directory locator",
        0,
    ),
    "locator at start": (lambda: _zip64(locator_offset=0), _CHECKED_RECORD, 0),
    "record missing": (
        lambda: _zip64(signature=b"PK\x06\x08"),
        _NOT_FOUND,
        _BAD_OFFSET,
    ),
    "multiple disks": (
        lambda: _zip64(disks=2),
        "zipfiles that span multiple disks are not supported",
        "zipfiles that span multiple disks are not supported",
    ),
}


def _skill_outcome(read: Callable[[], tuple[list[int], bytes]]) -> int | str:
    try:
        offsets, content = read()
    except zipfile.BadZipFile as exc:
        return str(exc)
    assert content == b"saved skill"
    [offset] = offsets
    return offset


@pytest.mark.parametrize("fixture", _ZIP64_ENDS)
def test_zip64_end_records_follow_each_python_release(
    monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    build, checked_outcome, legacy_outcome = _ZIP64_ENDS[fixture]
    data = build()

    def native() -> tuple[list[int], bytes]:
        with zipfile.ZipFile(io.BytesIO(data)) as reference:
            offsets = [info.header_offset for info in reference.infolist()]
            return offsets, reference.read("SKILL.md")

    def indexed() -> tuple[list[int], bytes]:
        with ZipIndex(data) as index:
            offsets = [info.header_offset for info in index.infos()]
            return offsets, index.read("SKILL.md")

    running = zip_index._checks_zip64_end()
    assert _skill_outcome(native) == (checked_outcome if running else legacy_outcome)
    for checked, expected in ((True, checked_outcome), (False, legacy_outcome)):
        monkeypatch.setattr(zip_index, "_checks_zip64_end", lambda c=checked: c)
        assert _skill_outcome(indexed) == expected


def _with_record_before_first(data: bytes, compress_size: int) -> bytes:
    """Add a copy of the first entry, with another size, before it."""
    first = data.index(b"PK\x01\x02")
    name_length = struct.unpack_from("<H", data, first + 28)[0]
    record = bytearray(data[first : first + 46 + name_length])
    struct.pack_into("<2L", record, 20, compress_size, compress_size)
    end = data.rindex(b"PK\x05\x06")
    count, size, offset = struct.unpack_from("<H2L", data, end + 10)
    tail = struct.pack(
        "<4s4H2LH",
        b"PK\x05\x06",
        0,
        0,
        count + 1,
        count + 1,
        size + len(record),
        offset,
        0,
    )
    return data[:first] + bytes(record) + data[first:end] + tail


def _member_reads(data: bytes) -> list[object]:
    with ZipIndex(data) as index:
        read = _index_reader(index)
        return [_member(read, info) for info in index.infos()]


def test_entries_that_share_a_header_end_at_the_next_header() -> None:
    shared = raw_zip([("same", b"1")] * 3, shared_header=True)
    assert _member_reads(shared) == [(b"1", [])] * 3
    # The first "a" claims data past the local header of "b". Python 3.13.16
    # warns and reads it with no bound; Python 3.13.0 also refuses the second
    # "a". Both entries named "a" end at the header of "b" here.
    data = _with_record_before_first(raw_zip([("a", b"1" * 40), ("b", b"2")]), 80)
    overlapped = (
        (zipfile.BadZipFile, "Overlapped entries: 'a' (possible zip bomb)"),
        [],
    )
    assert _member_reads(data) == [overlapped, (b"1" * 40, []), (b"2", [])]


def test_concurrent_first_use_reads_while_other_threads_capture_warnings() -> None:
    data = raw_zip([("SKILL.md", b"saved skill")])
    zip_index._checks_zip64_end.cache_clear()
    barrier = threading.Barrier(16)

    def read(worker: int) -> object:
        barrier.wait()
        with warnings.catch_warnings(record=bool(worker % 2)):
            with ZipIndex(data) as index:
                return index.read("SKILL.md")

    switch = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        for _ in range(10):
            zip_index._checks_zip64_end.cache_clear()
            with ThreadPoolExecutor(max_workers=16) as pool:
                assert list(pool.map(read, range(16))) == [b"saved skill"] * 16
    finally:
        sys.setswitchinterval(switch)


@pytest.mark.parametrize("failure", ["connect", "schema"])
def test_reader_closes_storage_when_its_creation_fails(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    data = raw_zip([("SKILL.md", b"body")])
    zip_index._checks_zip64_end()
    connection = sqlite3.connect("")
    failed = MagicMock(wraps=connection)
    error = sqlite3.OperationalError("storage failure")
    if failure == "connect":
        monkeypatch.setattr(sqlite3, "connect", MagicMock(side_effect=error))
    else:
        failed.executescript.side_effect = error
        monkeypatch.setattr(sqlite3, "connect", lambda _: failed)
    try:
        with pytest.raises(sqlite3.OperationalError, match="storage failure") as caught:
            ZipIndex(data)
        assert caught.value is error
        if failure == "schema":
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


def _with_local_header(data: bytes, offset: int, value: bytes) -> bytes:
    start = data.index(b"PK\x03\x04")
    return data[: start + offset] + value + data[start + offset + len(value) :]


def _with_flags(data: bytes, flags: int) -> bytes:
    flag_bytes = struct.pack("<H", flags)
    data = _with_local_header(data, 6, flag_bytes)
    start = data.index(b"PK\x01\x02")
    return data[: start + 8] + flag_bytes + data[start + 10 :]


def _with_record_field(data: bytes, offset: int, value: bytes) -> bytes:
    start = data.index(b"PK\x01\x02")
    return data[: start + offset] + value + data[start + offset + len(value) :]


def _zip64_extra(sizes: bytes) -> bytes:
    data = raw_zip([("a", b"1")], extra_bytes=len(sizes))
    data = data.replace(
        struct.pack("<HH", _EXTRA_ID, len(sizes)) + bytes(len(sizes)),
        struct.pack("<HH", 1, len(sizes)) + sizes,
    )
    return _with_record_field(data, 20, struct.pack("<2L", 0xFFFFFFFF, 0xFFFFFFFF))


def _unicode_path(value: bytes) -> bytes:
    data = raw_zip([("a", b"1")], extra_bytes=len(value))
    return data.replace(
        struct.pack("<HH", _EXTRA_ID, len(value)) + bytes(len(value)),
        struct.pack("<HH", 0x7075, len(value)) + value,
    )


_MEMBER_FAILURES: dict[str, Callable[[], bytes]] = {
    "bad local header magic": lambda: raw_zip([("a", b"1")]).replace(
        b"PK\x03\x04", b"PK\x03\x09"
    ),
    "truncated local header": lambda: _with_record_field(
        raw_zip([("a", b"1")]), 42, struct.pack("<L", 30)
    ),
    "header past the end": lambda: _with_record_field(
        raw_zip([("a", b"1")]), 42, struct.pack("<L", 1 << 20)
    ),
    "negative header offset": lambda: (
        raw_zip([("a", b"1")])[:-22]
        + struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, 52, 31, 0)
    ),
    "local name differs": lambda: _with_local_header(raw_zip([("a", b"1")]), 30, b"b"),
    "local extra field": lambda: _with_local_header(
        raw_zip([("a", b"123456")]), 28, struct.pack("<H", 2)
    ),
    "bad crc": lambda: _with_record_field(raw_zip([("a", b"1")]), 16, bytes(4)),
    "encrypted": lambda: _with_flags(raw_zip([("a", b"1")]), 0x801),
    "compressed patch": lambda: _with_flags(raw_zip([("a", b"1")]), 0x820),
    "strong encryption": lambda: _with_flags(raw_zip([("a", b"1")]), 0x840),
    "unsupported compression": lambda: _with_record_field(
        raw_zip([("a", b"1")]), 10, struct.pack("<H", 99)
    ),
    "cp437 name": lambda: _with_flags(raw_zip([("\u00e9", b"1")]), 0),
    "zip64 extra sizes": lambda: _zip64_extra(struct.pack("<2Q", 1, 1)),
    "zip64 extra missing a size": lambda: _zip64_extra(struct.pack("<Q", 1)),
    "unicode path, empty": lambda: _unicode_path(
        struct.pack("<BL", 1, zlib.crc32(b"a"))
    ),
    "unicode path, bad utf-8": lambda: _unicode_path(
        struct.pack("<BL", 1, zlib.crc32(b"a")) + b"\xff"
    ),
    "unicode path, short": lambda: _unicode_path(b"\x01\x02"),
    "unicode path, other crc": lambda: _unicode_path(
        struct.pack("<BL", 1, 7) + b"other"
    ),
}


@pytest.mark.parametrize("fixture", {**_MALFORMED, **_MEMBER_FAILURES})
def test_malformed_archives_fail_as_in_zipfile(fixture: str) -> None:
    data = {**_MALFORMED, **_MEMBER_FAILURES}[fixture]()
    assert _outcome(data, indexed=True) == _outcome(data, indexed=False)


def test_overlapped_entries_fail_as_in_zipfile() -> None:
    data = bytearray(raw_zip([("a", b"1" * 50), ("b", b"2")]))
    # Point the second entry into the first entry's data.
    second = data.rindex(b"PK\x01\x02")
    data[second + 42 : second + 46] = struct.pack("<L", 10)
    data = bytes(data)
    assert _outcome(data, indexed=True) == _outcome(data, indexed=False)
    with zipfile.ZipFile(io.BytesIO(data)) as reference:
        with pytest.raises(zipfile.BadZipFile, match="Overlapped entries"):
            reference.read("a")


def _mutated(rng: random.Random, data: bytes) -> bytes:
    mutated = bytearray(data)
    near_end = rng.random() < 0.5
    for _ in range(rng.randint(1, 3)):
        low = max(len(mutated) - 160, 0) if near_end else 0
        position = rng.randrange(low, len(mutated))
        roll = rng.random()
        if roll < 0.6:
            mutated[position] = rng.randrange(256)
        elif roll < 0.85:
            value = rng.choice([0, 0xFFFFFFFF, rng.randrange(len(mutated) + 1)])
            mutated[position : position + 4] = struct.pack("<L", value)
        else:
            del mutated[position : position + rng.randint(1, 8)]
    return bytes(mutated)


def test_mutated_archives_match_zipfile() -> None:
    bases = [
        _written(),
        b"prefix" + _written(),
        _unicode_extra(),
        _zip64(),
        _zip64(prefix=b"prefix", extensible=bytes(8)),
        raw_zip([("b", b"1"), ("a", b"2"), ("b", b"3")], comment_bytes=5),
    ]
    rng = random.Random(17)
    compared = 0
    for _ in range(600):
        data = _mutated(rng, rng.choice(bases))
        if _shares_header_offsets(data):
            continue
        compared += 1
        assert _outcome(data, indexed=True) == _outcome(data, indexed=False), data.hex()
    assert compared > 550


def _shares_header_offsets(data: bytes) -> bool:
    """Whether zipfile lists two entries at one local header offset."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as reference:
            offsets = [info.header_offset for info in reference.infolist()]
    except Exception:  # noqa: BLE001
        return False
    return len(set(offsets)) != len(offsets)


@pytest.mark.parametrize("offset", [2**63 - 1, 2**63, 2**64 - 1])
def test_header_offsets_past_sqlite_integers_fail_as_in_zipfile(offset: int) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("a")
        info.extra = struct.pack("<HHQ", 1, 8, offset)
        archive.writestr(info, b"x")
    data = output.getvalue()
    data = _with_record_field(data, 42, struct.pack("<L", 0xFFFFFFFF))
    assert _outcome(data, indexed=True) == _outcome(data, indexed=False)


def test_metadata_cap_refuses_before_any_entry_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = raw_zip([(f"{index}/", b"") for index in range(1000)])
    created: list[str] = []

    class CountingZipInfo(IndexedZipInfo):
        __slots__ = ()

        def __init__(
            self,
            filename: str = "NoName",
            date_time: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0),
        ) -> None:
            super().__init__(filename, date_time)
            created.append(filename)

    monkeypatch.setattr(zip_index, "IndexedZipInfo", CountingZipInfo)
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


@pytest.mark.parametrize("trailing_bytes", [65_535, 65_536, 65_537])
def test_comment_search_window_matches_installed_zipfile(trailing_bytes: int) -> None:
    data = raw_zip([("SKILL.md", b"kept")]) + bytes(trailing_bytes)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            expected = archive.read("SKILL.md")
    except zipfile.BadZipFile as error:
        with pytest.raises(zipfile.BadZipFile, match=str(error)):
            ZipIndex(data)
    else:
        with ZipIndex(data) as index:
            assert index.read("SKILL.md") == expected
