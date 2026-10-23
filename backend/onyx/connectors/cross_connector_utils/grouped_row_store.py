import sqlite3
from collections.abc import Callable, Iterable, Iterator
from typing import Generic, Self, TypeVar

from pydantic import BaseModel

# Groups one all_groups read loads at a time.
GROUP_READ_SIZE = 1_000

Row = TypeVar("Row", bound=BaseModel)

_SCHEMA = (
    "CREATE TABLE rows (seq INTEGER PRIMARY KEY, key TEXT NOT NULL, row TEXT NOT NULL);"
    "CREATE INDEX rows_by_key ON rows (key, seq);"
    "CREATE TABLE groups (seq INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE);"
)


class GroupedRowStore(Generic[Row]):
    """Rows a connector lists page by page but can only use once every row of
    a group is in, such as a mail thread's messages spread across folders.

    Rows live in an anonymous sqlite database, a temp file the OS removes
    even if the process dies. ``group`` numbers the groups by their first
    row's arrival, so a read by position is stable. A read passes each group
    through ``keep`` before the next one loads, so memory holds one whole
    group and a slice of trimmed ones, however many rows the store takes.

    Adds and ``group`` may run on one thread and reads on another, never at
    the same time, so the connection is shared without a lock.
    """

    def __init__(
        self,
        row_type: type[Row],
        group_key: Callable[[Row], str],
        keep: Callable[[list[Row]], list[Row]],
    ) -> None:
        self._row_type = row_type
        self._group_key = group_key
        self._keep = keep
        self._conn = sqlite3.connect("", check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self.grouped = False
        self.group_count = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def add(self, rows: Iterable[Row]) -> None:
        with self._conn:
            self._conn.executemany(
                "INSERT INTO rows (key, row) VALUES (?, ?)",
                ((self._group_key(row), row.model_dump_json()) for row in rows),
            )

    def group(self) -> None:
        with self._conn:
            self.group_count = self._conn.execute(
                "INSERT INTO groups (key) SELECT key FROM rows GROUP BY key "
                "ORDER BY MIN(seq)"
            ).rowcount
        self.grouped = True

    def groups(self, start: int, count: int) -> list[list[Row]]:
        """The ``count`` groups from 0-based ``start``, each its rows in the
        order they were added, passed through ``keep``."""
        cursor = self._conn.execute(
            "SELECT g.seq, r.row FROM groups g JOIN rows r ON r.key = g.key "
            "WHERE g.seq > ? AND g.seq <= ? ORDER BY g.seq, r.seq",
            (start, start + count),
        )
        groups: list[list[Row]] = []
        current: int | None = None
        rows: list[Row] = []
        for group_seq, row in cursor:
            if current is not None and group_seq != current:
                groups.append(self._keep(rows))
                rows = []
            current = group_seq
            rows.append(self._row_type.model_validate_json(row))
        if rows:
            groups.append(self._keep(rows))
        return groups

    def all_groups(self) -> Iterator[list[Row]]:
        for start in range(0, self.group_count, GROUP_READ_SIZE):
            yield from self.groups(start, GROUP_READ_SIZE)

    def close(self) -> None:
        self._conn.close()
