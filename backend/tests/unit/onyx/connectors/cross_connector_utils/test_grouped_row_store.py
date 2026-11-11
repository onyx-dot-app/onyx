"""The on-disk grouped row store: rows round-trip, groups come back in
first-added order with their rows in added order, reads are sliced, a read
passes each group through ``keep``, and closing releases the database. A
store of 300k rows across 100k groups reads back whole in slices."""

import sqlite3
from collections.abc import Callable, Iterator

import pytest
from pydantic import BaseModel

from onyx.connectors.cross_connector_utils import grouped_row_store
from onyx.connectors.cross_connector_utils.grouped_row_store import GroupedRowStore

LARGE_STORE_ROWS = 300_000
LARGE_STORE_GROUPS = 100_000


class _Row(BaseModel):
    group: str
    name: str
    tags: list[str] = []


def _all_rows(rows: list[_Row]) -> list[_Row]:
    return rows


def _store(
    keep: Callable[[list[_Row]], list[_Row]] = _all_rows,
) -> GroupedRowStore[_Row]:
    return GroupedRowStore(_Row, lambda row: row.group, keep=keep)


@pytest.fixture
def store() -> Iterator[GroupedRowStore[_Row]]:
    with _store() as store:
        yield store


def _names(groups: list[list[_Row]]) -> list[list[str]]:
    return [[row.name for row in rows] for rows in groups]


def test_groups_come_back_in_first_added_order_with_rows_intact(
    store: GroupedRowStore[_Row],
) -> None:
    store.add([_Row(group="b", name="b1", tags=["x"]), _Row(group="a", name="a1")])
    store.add([_Row(group="b", name="b2"), _Row(group="c", name="c1")])

    store.group()

    assert store.grouped
    assert store.group_count == 3
    groups = store.groups(0, 10)
    assert _names(groups) == [["b1", "b2"], ["a1"], ["c1"]]
    assert groups[0][0] == _Row(group="b", name="b1", tags=["x"])


def test_reads_are_sliced_and_cover_every_group_once(
    store: GroupedRowStore[_Row], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(grouped_row_store, "GROUP_READ_SIZE", 3)
    store.add([_Row(group=f"g{i}", name=f"r{i}") for i in range(7)])
    store.group()

    slices = [store.groups(start, 3) for start in (0, 3, 6, 9)]

    assert [len(s) for s in slices] == [3, 3, 1, 0]
    expected = [f"g{i}" for i in range(7)]
    assert [rows[0].group for s in slices for rows in s] == expected
    assert [rows[0].group for rows in store.all_groups()] == expected


def test_a_read_trims_each_group_with_keep() -> None:
    def keep_last_two(rows: list[_Row]) -> list[_Row]:
        return rows[-2:]

    with _store(keep=keep_last_two) as store:
        store.add([_Row(group="a", name=f"a{i}") for i in range(5)])
        store.add([_Row(group="b", name="b0")])
        store.group()

        assert _names(store.groups(0, 2)) == [["a3", "a4"], ["b0"]]


def test_a_long_group_is_folded_through_keep_as_it_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(grouped_row_store, "GROUP_FOLD_ROWS", 3)
    largest_input = 0

    def keep_last_two(rows: list[_Row]) -> list[_Row]:
        nonlocal largest_input
        largest_input = max(largest_input, len(rows))
        return rows[-2:]

    with _store(keep=keep_last_two) as store:
        store.add([_Row(group="a", name=f"a{i}") for i in range(20)])
        store.group()

        assert _names(store.groups(0, 1)) == [["a18", "a19"]]
    assert largest_input == 5


def test_close_releases_the_database() -> None:
    with _store() as store:
        store.add([_Row(group="a", name="a0")])

    with pytest.raises(sqlite3.ProgrammingError):
        store.groups(0, 1)


def test_a_store_the_size_of_a_large_mailbox_reads_back_in_slices(
    store: GroupedRowStore[_Row],
) -> None:
    store.add(
        _Row(group=f"g{i % LARGE_STORE_GROUPS}", name=f"r{i}")
        for i in range(LARGE_STORE_ROWS)
    )
    store.group()

    assert store.group_count == LARGE_STORE_GROUPS
    rows_per_group = LARGE_STORE_ROWS // LARGE_STORE_GROUPS
    seen = 0
    for rows in store.all_groups():
        assert len(rows) == rows_per_group
        seen += 1
    assert seen == LARGE_STORE_GROUPS
