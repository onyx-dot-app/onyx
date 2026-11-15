"""Regression coverage for the Drive connector's bounded conversion: at most
DRIVE_CONVERSION_MAX_IN_FLIGHT conversions are pending at a time, every file
converts once, and hierarchy-deferred files wait for their ancestor node before
converting."""

import threading
import time
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from typing import cast
from unittest.mock import MagicMock, patch

from onyx.connectors.google_drive.connector import (
    GoogleDriveConnector,
    _interleave_by_user,
)
from onyx.connectors.google_drive.models import (
    DriveRetrievalStage,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import Document, HierarchyNode
from onyx.utils.threadpool_concurrency import ThreadSafeDict, ThreadSafeSet

_BATCH = 10
_CONN_MODULE = "onyx.connectors.google_drive.connector"


def _make_connector() -> GoogleDriveConnector:
    connector = GoogleDriveConnector(include_my_drives=True)
    connector._ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector._primary_admin_email = "admin@example.com"
    connector.exclude_domain_link_only = False
    connector._retrieved_folder_and_drive_ids = set()
    return connector


def _make_checkpoint() -> GoogleDriveCheckpoint:
    return GoogleDriveCheckpoint(
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.DONE,
        completion_map=ThreadSafeDict(),
        retrieved_drive_file_ids=set(),
        has_more=False,
    )


def _make_file(idx: int, parent_id: str | None = None) -> RetrievedDriveFile:
    rf = MagicMock(spec=RetrievedDriveFile)
    rf.error = None
    rf.completion_stage = DriveRetrievalStage.DONE
    rf.user_email = f"user{idx}@example.com"
    rf.parent_id = parent_id
    drive_file: dict[str, object] = {"id": f"file_{idx}", "name": f"file_{idx}"}
    if parent_id is not None:
        drive_file["parents"] = [parent_id]
    rf.drive_file = drive_file
    return rf


class _Conversions:
    """Stands in for the per-file conversion: records which files converted
    and how many ran at once, and returns one stub Document per file."""

    def __init__(self, skip: Callable[[str], bool] = lambda _: False) -> None:
        self.converted_ids: list[str] = []
        self.peak_running = 0
        self._running = 0
        self._lock = threading.Lock()
        self._skip = skip

    def __call__(
        self, retrieved_file: RetrievedDriveFile, _context: object
    ) -> Document | None:
        file_id = str(retrieved_file.drive_file["id"])
        with self._lock:
            self._running += 1
            self.peak_running = max(self.peak_running, self._running)
            self.converted_ids.append(file_id)
        time.sleep(0.002)
        with self._lock:
            self._running -= 1
        if self._skip(file_id):
            return None
        doc = MagicMock(spec=Document)
        doc.id = file_id
        return doc


@contextmanager
def _patched(
    connector: GoogleDriveConnector,
    conversions: _Conversions,
    ancestors: Callable[..., list[HierarchyNode]] | None = None,
    batch_size: int = _BATCH,
    max_in_flight: int = 4,
) -> Iterator[None]:
    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", batch_size),
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_WORKERS", 2),
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_MAX_IN_FLIGHT", max_in_flight),
        patch.object(
            connector,
            "_get_new_ancestors_for_files",
            side_effect=ancestors or (lambda **_: []),
        ),
        patch.object(
            connector, "_convert_retrieved_file_to_document", side_effect=conversions
        ),
    ):
        yield


def _convert(
    connector: GoogleDriveConnector, files: list[RetrievedDriveFile]
) -> list[Document | HierarchyNode]:
    return cast(
        list[Document | HierarchyNode],
        list(
            connector._convert_retrieved_files_to_documents(
                iter(files), _make_checkpoint(), include_permissions=False
            )
        ),
    )


def test_converts_every_file_with_bounded_concurrency() -> None:
    connector = _make_connector()
    conversions = _Conversions()
    n_files = _BATCH * 4 + 3

    with _patched(connector, conversions, max_in_flight=3):
        out = _convert(connector, [_make_file(i) for i in range(n_files)])

    # Every file becomes exactly one document; nothing dropped or duplicated.
    assert sorted(conversions.converted_ids) == sorted(
        f"file_{i}" for i in range(n_files)
    )
    assert len(out) == n_files
    # The pool never runs more than its workers.
    assert conversions.peak_running <= 2


def test_yields_incrementally_without_draining_whole_drive() -> None:
    connector = _make_connector()
    n_files = _BATCH * 5
    consumed = {"count": 0}

    def _counting_iter() -> Iterator[RetrievedDriveFile]:
        for i in range(n_files):
            consumed["count"] += 1
            yield _make_file(i)

    # A window smaller than a sub-batch: submitting the first sub-batch blocks
    # until a conversion finishes, and that document is yielded at once.
    with _patched(connector, _Conversions(), max_in_flight=_BATCH // 2):
        gen = connector._convert_retrieved_files_to_documents(
            _counting_iter(), _make_checkpoint(), include_permissions=False
        )
        first = next(gen)
        # Closing it shuts down the conversion pool.
        cast(Generator[object, None, None], gen).close()

    assert isinstance(first, MagicMock)
    assert consumed["count"] == _BATCH


def test_hierarchy_nodes_precede_their_documents() -> None:
    connector = _make_connector()
    n_files = _BATCH * 2

    def _node_per_batch(**kwargs: object) -> list[HierarchyNode]:
        files = cast("list[RetrievedDriveFile]", kwargs["files"])
        seen = cast("ThreadSafeSet[str]", kwargs["seen_hierarchy_node_raw_ids"])
        folder = files[0].drive_file["parents"]
        node_id = cast(list[str], folder)[0]
        seen.add(node_id)
        return [MagicMock(spec=HierarchyNode, raw_node_id=node_id)]

    files = [_make_file(i, parent_id=f"folder_{i // _BATCH}") for i in range(n_files)]
    with _patched(connector, _Conversions(), ancestors=_node_per_batch):
        out = _convert(connector, files)

    emitted: set[str] = set()
    for item in out:
        if isinstance(item, HierarchyNode):
            emitted.add(item.raw_node_id)
            continue
        file_index = int(str(item.id).removeprefix("file_"))
        assert f"folder_{file_index // _BATCH}" in emitted
    assert len([x for x in out if not isinstance(x, HierarchyNode)]) == n_files


def test_defers_documents_until_ancestor_available() -> None:
    connector = _make_connector()
    conversions = _Conversions()
    parent_id = "folder_1"
    called = False

    def _fake_ancestors(**kwargs: object) -> list[HierarchyNode]:
        # First invocation: ancestors unavailable; second invocation resolves the folder.
        nonlocal called
        if not called:
            called = True
            return []
        seen = cast(ThreadSafeSet[str], kwargs["seen_hierarchy_node_raw_ids"])
        seen.add(parent_id)
        return [MagicMock(spec=HierarchyNode, raw_node_id=parent_id)]

    with _patched(connector, conversions, ancestors=_fake_ancestors, batch_size=1):
        out = _convert(
            connector,
            [_make_file(0, parent_id=parent_id), _make_file(1, parent_id=parent_id)],
        )

    # file_0 waited for its folder; both convert after the node appears.
    assert isinstance(out[0], HierarchyNode)
    assert len(out) == 3
    assert sorted(conversions.converted_ids) == ["file_0", "file_1"]


def test_filtered_tail_still_yields_finished_conversions() -> None:
    connector = _make_connector()
    connector.exclude_domain_link_only = True
    conversions = _Conversions()
    n_tail = 20
    consumed = {"count": 0}

    def _files() -> Iterator[RetrievedDriveFile]:
        for i in range(2):
            consumed["count"] += 1
            yield _make_file(i)
        # Let both submitted conversions finish before the filtered tail.
        deadline = time.monotonic() + 5
        while len(conversions.converted_ids) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        time.sleep(0.05)
        for i in range(2, 2 + n_tail):
            consumed["count"] += 1
            yield _make_file(i)

    # A window larger than the sub-batch, so submission never waits.
    with (
        _patched(connector, conversions, batch_size=2, max_in_flight=10),
        patch(
            f"{_CONN_MODULE}.has_link_only_permission",
            side_effect=lambda drive_file: (
                int(str(drive_file["id"]).removeprefix("file_")) >= 2
            ),
        ),
    ):
        gen = connector._convert_retrieved_files_to_documents(
            _files(), _make_checkpoint(), include_permissions=False
        )
        next(gen)
        consumed_at_first = consumed["count"]
        rest = list(gen)

    # The first document arrives while the filtered tail is still listing.
    assert consumed_at_first < 2 + n_tail
    assert len(rest) == 1


def test_force_flush_converts_files_whose_folder_never_resolves() -> None:
    connector = _make_connector()
    conversions = _Conversions()
    n_files = _BATCH * 2 + 2

    with _patched(connector, conversions):
        out = _convert(
            connector, [_make_file(i, parent_id="folder") for i in range(n_files)]
        )

    assert len(out) == n_files
    assert len(conversions.converted_ids) == n_files


def test_deferred_files_wait_for_their_folder_then_all_resolve() -> None:
    connector = _make_connector()
    conversions = _Conversions()
    n_files = 300  # large enough to rule out any fixed-size deferral cap
    folder = "shared_folder"

    # The folder node is emitted only when the LAST file is walked, so all 300
    # files defer first. None may be force-converted early; every one must wait
    # and then resolve once the folder appears (its node ahead of every doc).
    def _fake_ancestors(**kwargs: object) -> list[HierarchyNode]:
        files = cast("list[RetrievedDriveFile]", kwargs["files"])
        seen = cast("ThreadSafeSet[str]", kwargs["seen_hierarchy_node_raw_ids"])
        if any(f.drive_file["id"] == f"file_{n_files - 1}" for f in files):
            seen.add(folder)
            return [MagicMock(spec=HierarchyNode, raw_node_id=folder)]
        return []

    with _patched(connector, conversions, ancestors=_fake_ancestors):
        out = _convert(
            connector, [_make_file(i, parent_id=folder) for i in range(n_files)]
        )

    nodes = [x for x in out if isinstance(x, HierarchyNode)]
    docs = [x for x in out if not isinstance(x, HierarchyNode)]
    assert len(docs) == n_files  # nothing dropped or orphaned by a cap
    assert len(nodes) == 1
    assert isinstance(out[0], HierarchyNode)  # folder node precedes every document
    assert conversions.peak_running <= 2  # the release still converts boundedly


def test_skipped_conversions_are_dropped_not_counted() -> None:
    connector = _make_connector()
    n_files = 6

    # Conversion returns None for skipped files (e.g. empty/unsupported); those
    # must be dropped, not emitted: the batching must not assume 1 doc per file.
    def _is_even(file_id: str) -> bool:
        return int(file_id.removeprefix("file_")) % 2 == 0

    with _patched(connector, _Conversions(skip=_is_even)):
        out = _convert(connector, [_make_file(i) for i in range(n_files)])

    assert len(out) == n_files // 2  # only odd-indexed files produced a document


def test_interleave_takes_users_in_turn_within_the_lookahead() -> None:
    files = [_make_file(i) for i in range(6)]
    for f, user in zip(files, ["a", "a", "a", "b", "b", "c"], strict=True):
        f.user_email = user
    pulled = {"count": 0}

    def _listing() -> Iterator[RetrievedDriveFile]:
        for f in files:
            pulled["count"] += 1
            yield f

    interleaved = _interleave_by_user(_listing(), lookahead=4)
    first = next(interleaved)
    # Reading stops at the lookahead, not at the end of the listing.
    assert pulled["count"] == 4
    order = [first.user_email] + [f.user_email for f in interleaved]
    assert order == ["a", "b", "a", "b", "c", "a"]


def test_interleave_yields_every_file_once_and_keeps_a_users_order() -> None:
    files = [_make_file(i) for i in range(50)]
    for index, f in enumerate(files):
        f.user_email = f"user{index % 7 if index < 30 else 0}"

    out = list(_interleave_by_user(iter(files), lookahead=5))

    assert sorted(f.drive_file["id"] for f in out) == sorted(
        f.drive_file["id"] for f in files
    )
    for user in {f.user_email for f in files}:
        mine = [f.drive_file["id"] for f in files if f.user_email == user]
        assert [f.drive_file["id"] for f in out if f.user_email == user] == mine


def test_checkpoint_load_submits_conversions_in_user_turns() -> None:
    connector = _make_connector()
    conversions = _Conversions()
    # Each partition lists as one user, so the listing comes in user blocks.
    users = ["a"] * 4 + ["b"] * 2 + ["c"] * 2
    files = [_make_file(i) for i in range(len(users))]
    for f, user in zip(files, users, strict=True):
        f.user_email = user

    # One worker runs conversions in the order the runner gets them.
    with (
        _patched(connector, conversions),
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_WORKERS", 1),
        patch.object(connector, "_fetch_drive_items", return_value=iter(files)),
    ):
        out = list(
            connector._load_from_checkpoint(
                0, 1, _make_checkpoint(), include_permissions=False
            )
        )

    user_of = {str(f.drive_file["id"]): f.user_email for f in files}
    assert [user_of[file_id] for file_id in conversions.converted_ids] == [
        "a",
        "b",
        "c",
        "a",
        "b",
        "c",
        "a",
        "a",
    ]
    assert len(out) == len(files)
