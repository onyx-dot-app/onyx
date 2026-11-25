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


def _folder_bytes(
    held: dict[str, FileEntry],
    writing: dict[str, int],
    plan: tuple[list[str], list[_File]],
) -> int:
    """The most bytes that attachments/search/ can hold after the plan's
    deletes, whichever of the running and planned writes land. A write that
    fails keeps what is at its path."""
    evicted, fitting = plan
    sizes = {path: entry.size for path, entry in held.items() if path not in evicted}
    for path, size in [
        *writing.items(),
        *((write.path, write.size) for write in fitting),
    ]:
        sizes[path] = max(sizes.get(path, 0), size)
    return sum(sizes.values())


@pytest.mark.parametrize("replaced_protected", [False, True])
def test_a_skipped_replacement_keeps_its_old_copy_under_the_cap(
    replaced_protected: bool,
) -> None:
    held = {
        entry.path: entry
        for entry in (_entry("offered", 8, 90), _entry("small", 1, 60))
    }
    protected = {"attachments/search/offered"}
    if replaced_protected:
        protected.add("attachments/search/small")
    plan = _evictions(held, {}, [_write("small", 3), _write("new", 2)], protected)
    assert _folder_bytes(held, {}, plan) <= 10
    if replaced_protected:
        # The old copy stays, so the new file does not fit.
        assert plan == ([], [])
    else:
        assert plan == (["attachments/search/small"], [_write("new", 2)])


@pytest.mark.parametrize("replaced_protected", [False, True])
def test_one_of_two_grown_replacements_fits_under_the_cap(
    monkeypatch: pytest.MonkeyPatch, replaced_protected: bool
) -> None:
    mib = 1024 * 1024
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 1024 * mib)
    held = {
        entry.path: entry
        for entry in (
            _entry("offered", 900 * mib, 90),
            _entry("a", 60 * mib, 60),
            _entry("b", 60 * mib, 30),
        )
    }
    protected = {"attachments/search/offered"}
    if replaced_protected:
        protected |= {"attachments/search/a", "attachments/search/b"}
    plan = _evictions(
        held, {}, [_write("a", 70 * mib), _write("b", 70 * mib)], protected
    )
    assert _folder_bytes(held, {}, plan) <= 1024 * mib
    if replaced_protected:
        assert plan == ([], [])
    else:
        assert plan == (["attachments/search/b"], [_write("a", 70 * mib)])


@pytest.mark.parametrize("replaced_protected", [False, True])
def test_a_shrunk_replacement_makes_no_room_until_it_lands(
    monkeypatch: pytest.MonkeyPatch, replaced_protected: bool
) -> None:
    mib = 1024 * 1024
    monkeypatch.setattr(file_copies, "MAX_CHAT_SEARCH_BYTES", 1024 * mib)
    held = {
        entry.path: entry
        for entry in (_entry("offered", 900 * mib, 90), _entry("big", 100 * mib, 60))
    }
    protected = {"attachments/search/offered"}
    if replaced_protected:
        protected.add("attachments/search/big")
    plan = _evictions(
        held, {}, [_write("big", 10 * mib), _write("new", 100 * mib)], protected
    )
    assert _folder_bytes(held, {}, plan) <= 1024 * mib
    assert plan == ([], [_write("big", 10 * mib)])


@pytest.mark.parametrize("replaced_protected", [False, True])
def test_a_running_shrunk_replacement_keeps_its_listed_bytes(
    replaced_protected: bool,
) -> None:
    held = {
        entry.path: entry for entry in (_entry("offered", 6, 90), _entry("big", 4, 60))
    }
    protected = {"attachments/search/offered"}
    if replaced_protected:
        protected.add("attachments/search/big")
    writing = {"attachments/search/big": 1}
    plan = _evictions(held, writing, [_write("new", 3)], protected)
    assert _folder_bytes(held, writing, plan) <= 10
    assert plan == ([], [])
