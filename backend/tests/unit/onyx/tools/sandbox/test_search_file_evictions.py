"""The eviction plan of a chat's search result files (`file_copies._evictions`):
which writes fit under the cap and which older files make room for them."""

from datetime import datetime, timedelta, timezone

import pytest

from onyx.microvm.models import FileEntry, FileType
from onyx.tools.tool_implementations.sandbox import file_copies
from onyx.tools.tool_implementations.sandbox.file_copies import _evictions, _File

_NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def _entry(name: str, size: int, age_minutes: int | None) -> FileEntry:
    return FileEntry(
        path=f"attachments/search/{name}",
        name=name,
        type=FileType.REGULAR,
        size=size,
        mode=0o644,
        modified_at=None
        if age_minutes is None
        else _NOW - timedelta(minutes=age_minutes),
        link_target="",
    )


def _write(name: str, size: int) -> _File:
    return _File(f"attachments/search/{name}", f"id-{name}", size)


@pytest.fixture(autouse=True)
def cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 10)


def test_the_oldest_files_make_room_and_no_more() -> None:
    held = {
        entry.path: entry
        for entry in (
            _entry("old", 4, 30),
            _entry("older", 4, 60),
            _entry("undated", 4, None),
        )
    }
    evicted, fitting = _evictions(held, {}, [_write("new", 4)], set())
    assert evicted == ["attachments/search/older", "attachments/search/old"]
    assert fitting == [_write("new", 4)]


def test_protected_files_and_earlier_writes_stay_and_count() -> None:
    held = {
        entry.path: entry
        for entry in (_entry("offered", 4, 90), _entry("other", 2, 10))
    }
    protected = {"attachments/search/offered", "attachments/search/running"}
    # The running write is not listed yet; it still holds its 4 bytes.
    writing = {"attachments/search/running": 4}
    evicted, fitting = _evictions(
        held, writing, [_write("a", 2), _write("b", 1)], protected
    )
    assert fitting == [_write("a", 2)]
    assert evicted == ["attachments/search/other"]


def test_no_write_that_fits_deletes_nothing() -> None:
    held = {"attachments/search/old": _entry("old", 9, 60)}
    assert _evictions(held, {}, [_write("huge", 11)], set()) == ([], [])


def test_a_rewritten_path_counts_once() -> None:
    # A file whose listed copy has another size is replaced, not added.
    held = {"attachments/search/same": _entry("same", 3, 60)}
    protected = {"attachments/search/same"}
    assert _evictions(held, {}, [_write("same", 10)], protected) == (
        [],
        [_write("same", 10)],
    )
