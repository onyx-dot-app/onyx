"""Regression coverage for the Drive connector's inline conversion: at most
DRIVE_CONVERSION_MAX_IN_FLIGHT conversions are pending at a time, every file
converts once and does not wait for its folder, and conversions take the
listing's users in turn."""

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
from onyx.connectors.google_drive.constants import DRIVE_FOLDER_TYPE
from onyx.connectors.google_drive.models import (
    DriveListingState,
    GDriveMimeType,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
)
from onyx.connectors.google_drive.source_operations import (
    GoogleDriveSourceOperations,
)
from onyx.connectors.models import Document, HierarchyNode

_BATCH = 10
_CONN_MODULE = "onyx.connectors.google_drive.connector"


def _make_connector() -> GoogleDriveConnector:
    connector = GoogleDriveConnector(include_my_drives=True)
    connector._ops = MagicMock(spec=GoogleDriveSourceOperations)
    connector._primary_admin_email = "admin@example.com"
    connector.exclude_domain_link_only = False
    return connector


def _make_checkpoint() -> GoogleDriveCheckpoint:
    return GoogleDriveCheckpoint(retrieved_drive_file_ids=set(), has_more=False)


def _listing() -> DriveListingState:
    """A listing with no partition left to list."""
    return DriveListingState(window_t0=0, window_t1=0)


def _make_file(idx: int, parent_id: str | None = None) -> RetrievedDriveFile:
    rf = MagicMock(spec=RetrievedDriveFile)
    rf.error = None
    rf.user_email = f"user{idx}@example.com"
    rf.parent_id = parent_id
    drive_file: dict[str, object] = {
        "id": f"file_{idx}",
        "name": f"file_{idx}",
        "mimeType": GDriveMimeType.DOC.value,
    }
    if parent_id is not None:
        drive_file["parents"] = [parent_id]
    rf.drive_file = drive_file
    return rf


def _make_folder(folder_id: str) -> RetrievedDriveFile:
    rf = MagicMock(spec=RetrievedDriveFile)
    rf.error = None
    rf.user_email = "user@example.com"
    rf.parent_id = None
    rf.drive_file = {"id": folder_id, "name": folder_id, "mimeType": DRIVE_FOLDER_TYPE}
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
    folder_nodes: Callable[..., list[HierarchyNode]] | None = None,
    batch_size: int = _BATCH,
    max_in_flight: int = 4,
) -> Iterator[None]:
    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", batch_size),
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_WORKERS", 2),
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_MAX_IN_FLIGHT", max_in_flight),
        patch.object(
            connector,
            "_listed_folder_nodes",
            side_effect=folder_nodes or (lambda *_args, **_kwargs: []),
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
                iter(files), _make_checkpoint(), _listing(), include_permissions=False
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

    # Each file is submitted when it is listed. Once the window is full, the
    # next submission waits for a conversion, and that document is yielded.
    max_in_flight = _BATCH // 2
    with _patched(connector, _Conversions(), max_in_flight=max_in_flight):
        gen = connector._convert_retrieved_files_to_documents(
            _counting_iter(), _make_checkpoint(), _listing(), include_permissions=False
        )
        first = next(gen)
        # Closing it shuts down the conversion pool.
        cast(Generator[object, None, None], gen).close()

    assert isinstance(first, MagicMock)
    assert consumed["count"] <= max_in_flight + 1


def test_files_do_not_wait_for_their_folder() -> None:
    connector = _make_connector()
    conversions = _Conversions()
    node = MagicMock(spec=HierarchyNode, raw_node_id="folder")
    flushed: list[tuple[list[str], list[str]]] = []

    def _folder_nodes(
        _listing_state: DriveListingState,
        _checkpoint: GoogleDriveCheckpoint,
        folders: list[RetrievedDriveFile],
        files: list[RetrievedDriveFile],
        *_args: object,
        **_kwargs: object,
    ) -> list[HierarchyNode]:
        flushed.append(
            (
                [str(f.drive_file["id"]) for f in folders],
                [str(f.drive_file["id"]) for f in files],
            )
        )
        return [node] if folders else []

    # The folder comes after its files in the stream.
    files = [_make_file(i, parent_id="folder") for i in range(3)]
    with _patched(connector, conversions, folder_nodes=_folder_nodes):
        out = _convert(connector, [*files, _make_folder("folder")])

    assert sorted(conversions.converted_ids) == ["file_0", "file_1", "file_2"]
    assert [item for item in out if isinstance(item, HierarchyNode)] == [node]
    assert len(out) == 4
    # The folder and the files' parents are recorded in one flush.
    assert flushed == [(["folder"], ["file_0", "file_1", "file_2"])]


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
            "onyx.connectors.google_drive.doc_conversion.has_link_only_permission",
            side_effect=lambda drive_file: (
                int(str(drive_file["id"]).removeprefix("file_")) >= 2
            ),
        ),
    ):
        gen = connector._convert_retrieved_files_to_documents(
            _files(), _make_checkpoint(), _listing(), include_permissions=False
        )
        next(gen)
        consumed_at_first = consumed["count"]
        rest = list(gen)

    # The first document arrives while the filtered tail is still listing.
    assert consumed_at_first < 2 + n_tail
    assert len(rest) == 1


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
        patch.object(connector, "_plan_listing", return_value=_listing()),
        patch.object(connector, "_fetch_drive_items", return_value=(f for f in files)),
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
