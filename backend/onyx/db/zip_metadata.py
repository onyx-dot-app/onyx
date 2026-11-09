"""Anonymous SQLite storage for ZIP metadata and validated bundle paths."""

import sqlite3
import zipfile
from collections.abc import Iterable, Iterator
from typing import Self

_SCHEMA = (
    "CREATE TABLE entries (seq INTEGER PRIMARY KEY, name BLOB NOT NULL, "
    "record INTEGER NOT NULL, header BLOB NOT NULL, end_offset BLOB);"
    "CREATE INDEX entries_by_name ON entries (name, seq);"
    "CREATE INDEX entries_by_header ON entries (header, seq);"
)

# Header offsets come from 64-bit ZIP64 fields plus the prepended length, so
# they can fall outside SQLite's 64-bit integers. Biased big-endian bytes keep
# their order; zipfile lists such entries and fails only when one is read.
_OFFSET_BIAS = 1 << 88
_OFFSET_BYTES = 12


def _offset_key(offset: int) -> bytes:
    return (offset + _OFFSET_BIAS).to_bytes(_OFFSET_BYTES, "big")


def _offset(key: bytes) -> int:
    return int.from_bytes(key, "big") - _OFFSET_BIAS


# Each entry's data must end before the next greater local header offset, or
# before the central directory. Entries that share a header offset all get the
# same end. zipfile instead gives all but one of them their own header offset:
# Python 3.13.0 then fails to open them, and 3.13.16 warns and reads them with
# no bound at all. This rule reads every shared entry that 3.13.16 reads within
# the bound, and refuses the data that would run into another local header.
_END_OFFSETS = (
    "UPDATE entries SET end_offset = COALESCE(("
    "SELECT MIN(later.header) FROM entries AS later "
    "WHERE later.header > entries.header), ?)"
)


class ZipEntryStore:
    """Disk-backed ZIP record offsets; ZIP parsing stays with the caller."""

    def __init__(self) -> None:
        self._db = sqlite3.connect("")
        try:
            self._db.executescript(_SCHEMA)
        except BaseException:
            self._db.close()
            raise

    def populate(
        self,
        entries: Iterable[tuple[int, bytes, int, int]],
        *,
        directory_start: int,
    ) -> None:
        with self._db:
            self._db.executemany(
                "INSERT INTO entries VALUES (?, ?, ?, ?, NULL)",
                (
                    (seq, name, record, _offset_key(header))
                    for seq, name, record, header in entries
                ),
            )
            self._db.execute(_END_OFFSETS, (_offset_key(directory_start),))

    def entries(self, *, by_name: bool = False) -> Iterator[tuple[int, int]]:
        query = (
            "SELECT record, end_offset FROM entries ORDER BY name, seq"
            if by_name
            else "SELECT record, end_offset FROM entries ORDER BY seq"
        )
        for record, end_offset in self._db.execute(query):
            yield record, _offset(end_offset)

    def find(self, name: str) -> tuple[int, int] | None:
        row = self._db.execute(
            "SELECT record, end_offset FROM entries WHERE name = ? ORDER BY seq DESC LIMIT 1",
            (name.encode(),),
        ).fetchone()
        return None if row is None else (row[0], _offset(row[1]))

    def close(self) -> None:
        self._db.close()


class SpooledZipInfos:
    """Written ZIP entries, kept in SQLite until the central directory is written.

    Each row holds the ZipInfo fields of one central directory record.
    """

    def __init__(self) -> None:
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


class DiskPathSet:
    """Paths kept in an anonymous SQLite database, a temp file."""

    def __init__(self) -> None:
        self._db = sqlite3.connect("")
        try:
            self._db.execute("CREATE TABLE paths (path TEXT PRIMARY KEY) WITHOUT ROWID")
        except BaseException:
            self._db.close()
            raise

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._db.close()

    def add(self, path: str) -> None:
        self._db.execute("INSERT OR IGNORE INTO paths VALUES (?)", (path,))

    def __contains__(self, path: str) -> bool:
        query = "SELECT 1 FROM paths WHERE path = ?"
        return self._db.execute(query, (path,)).fetchone() is not None
