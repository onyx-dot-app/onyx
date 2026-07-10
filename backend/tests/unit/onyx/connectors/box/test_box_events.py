"""Unit tests for the incremental (events-based) index path.

Steady-state short-window polls of a whole-enterprise connector should consume
the Box enterprise events stream instead of re-crawling the whole folder tree,
fetching only the files that actually changed.
"""

from datetime import datetime, timezone
from typing import cast

from box_sdk_gen import BoxClient
from box_sdk_gen.schemas.file import FilePathCollectionField
from box_sdk_gen.schemas.file_full import FileFull
from box_sdk_gen.schemas.folder_full import FolderFull
from box_sdk_gen.schemas.folder_mini import FolderMini
from box_sdk_gen.schemas.items import Items
from box_sdk_gen.schemas.user_mini import UserMini

from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.box.models import BoxTraversalMode
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    TextSection,
)
from tests.unit.onyx.connectors.box.fake_box_client import (
    FakeBoxClient,
    make_events_page,
)

_OWNER = UserMini(id="u1", name="Alice", login="alice@example.com")
_MODIFIED = datetime(2024, 6, 1, tzinfo=timezone.utc)

# steady-state hourly poll window (well under the 7-day events threshold)
_NOW = datetime(2024, 6, 2, tzinfo=timezone.utc).timestamp()
_HOUR_AGO = _NOW - 3600


def _file_with_parent(file_id: str, name: str) -> FileFull:
    """A file living under folder 200 ('Sub'), itself under root."""
    return FileFull(
        id=file_id,
        name=name,
        size=10,
        modified_at=_MODIFIED,
        created_at=_MODIFIED,
        owned_by=_OWNER,
        parent=FolderMini(id="200", name="Sub"),
        path_collection=FilePathCollectionField(
            total_count=2,
            entries=[
                FolderMini(id="0", name="All Files"),
                FolderMini(id="200", name="Sub"),
            ],
        ),
    )


def _make_events_connector(
    event_pages: list,
    files_by_id: dict[str, FileFull],
    file_contents: dict[str, bytes],
    file_fetch_fail_status_by_id: dict[str, int] | None = None,
    events_fail_status: int | None = None,
) -> tuple[BoxConnector, FakeBoxClient]:
    fake = FakeBoxClient(
        folders_by_id={
            "0": FolderFull(id="0", name="All Files"),
            "200": FolderFull(id="200", name="Sub"),
        },
        # pages present so a full-crawl fallback can still run
        pages={
            ("0", None): Items(
                entries=[FolderMini(id="200", name="Sub")], next_marker=None
            ),
            ("200", None): Items(entries=[], next_marker=None),
        },
        file_contents=file_contents,
        files_by_id=files_by_id,
        file_fetch_fail_status_by_id=file_fetch_fail_status_by_id,
        event_pages=event_pages,
        events_fail_status=events_fail_status,
    )
    connector = BoxConnector()  # whole-enterprise (root)
    connector._content_client = cast(BoxClient, fake)
    connector._enterprise_client = cast(BoxClient, fake)
    return connector, fake


def _run(
    connector: BoxConnector,
    start: float,
    end: float,
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], BoxTraversalMode | None]:
    checkpoint = connector.build_dummy_checkpoint()
    outputs: list[Document | HierarchyNode | ConnectorFailure] = []
    mode = None
    iterations = 0
    while checkpoint.has_more:
        iterations += 1
        assert iterations < 100
        generator = connector.load_from_checkpoint(start, end, checkpoint)
        while True:
            try:
                outputs.append(next(generator))
            except StopIteration as e:
                checkpoint = connector.validate_checkpoint_json(
                    e.value.model_dump_json()
                )
                mode = checkpoint.mode
                break
    return outputs, mode


def test_events_path_indexes_only_changed_files() -> None:
    connector, fake = _make_events_connector(
        event_pages=[make_events_page(["1", "2"], next_stream_position=None)],
        files_by_id={
            "1": _file_with_parent("1", "changed_a.txt"),
            "2": _file_with_parent("2", "changed_b.txt"),
        },
        file_contents={"1": b"alpha", "2": b"bravo"},
    )
    outputs, mode = _run(connector, _HOUR_AGO, _NOW)

    assert mode == BoxTraversalMode.EVENTS
    docs = {d.id for d in outputs if isinstance(d, Document)}
    assert docs == {"box-file-1", "box-file-2"}

    # only the two changed files were fetched — NOT a full tree crawl
    assert sorted(fake.files.fetch_calls) == ["1", "2"]
    # the connector listed no folders in events mode
    assert fake.folders.listing_calls == []

    # the changed file's parent folder is still surfaced as a hierarchy node
    node_ids = {n.raw_node_id for n in outputs if isinstance(n, HierarchyNode)}
    assert node_ids == {"200"}

    doc1 = next(d for d in outputs if isinstance(d, Document) and d.id == "box-file-1")
    assert doc1.metadata["path"] == "Sub"
    assert doc1.parent_hierarchy_raw_node_id == "200"
    section = doc1.sections[0]
    assert isinstance(section, TextSection)
    assert section.text == "alpha"


def test_events_path_paginates_and_dedups_repeated_files() -> None:
    # file "1" appears on both pages (edited twice in the window); it must be
    # fetched/indexed once.
    connector, fake = _make_events_connector(
        event_pages=[
            make_events_page(["1", "2"], next_stream_position="pos1"),
            make_events_page(["1", "3"], next_stream_position="pos2"),
            make_events_page([], next_stream_position="pos2"),
        ],
        files_by_id={
            "1": _file_with_parent("1", "a.txt"),
            "2": _file_with_parent("2", "b.txt"),
            "3": _file_with_parent("3", "c.txt"),
        },
        file_contents={"1": b"a", "2": b"b", "3": b"c"},
    )
    outputs, mode = _run(connector, _HOUR_AGO, _NOW)

    assert mode == BoxTraversalMode.EVENTS
    docs = [d.id for d in outputs if isinstance(d, Document)]
    assert sorted(docs) == ["box-file-1", "box-file-2", "box-file-3"]
    assert docs.count("box-file-1") == 1
    assert fake.files.fetch_calls.count("1") == 1
    # parent node 200 yielded once across the whole run
    node_ids = [n.raw_node_id for n in outputs if isinstance(n, HierarchyNode)]
    assert node_ids.count("200") == 1
    # pagination advanced through the stream positions
    assert fake.events.calls == [None, "pos1", "pos2"]


def test_events_path_skips_inaccessible_or_deleted_files() -> None:
    # 403 (not visible to indexing user) and 404 (already deleted) are skipped
    # silently — pruning reconciles deletions.
    connector, fake = _make_events_connector(
        event_pages=[make_events_page(["1", "2", "3"], next_stream_position=None)],
        files_by_id={"2": _file_with_parent("2", "ok.txt")},
        file_contents={"2": b"ok"},
        file_fetch_fail_status_by_id={"1": 403, "3": 404},
    )
    outputs, _ = _run(connector, _HOUR_AGO, _NOW)
    docs = {d.id for d in outputs if isinstance(d, Document)}
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert docs == {"box-file-2"}
    assert failures == []


def test_events_path_surfaces_unexpected_fetch_error_as_failure() -> None:
    connector, _ = _make_events_connector(
        event_pages=[make_events_page(["1"], next_stream_position=None)],
        files_by_id={},
        file_contents={},
        file_fetch_fail_status_by_id={"1": 500},
    )
    outputs, _ = _run(connector, _HOUR_AGO, _NOW)
    failures = [o for o in outputs if isinstance(o, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == "box-file-1"


def test_events_fetch_failure_falls_back_to_full_crawl() -> None:
    # if the events API itself errors (e.g. missing admin scope), the run must
    # fall back to a full crawl rather than silently index nothing.
    connector, fake = _make_events_connector(
        event_pages=[],
        files_by_id={},
        file_contents={},
        events_fail_status=403,
    )
    _, mode = _run(connector, _HOUR_AGO, _NOW)
    assert mode == BoxTraversalMode.FULL
    # the fallback actually crawled folders
    assert fake.folders.listing_calls != []


def test_wide_window_uses_full_crawl_not_events() -> None:
    connector, fake = _make_events_connector(
        event_pages=[make_events_page(["1"], next_stream_position=None)],
        files_by_id={"1": _file_with_parent("1", "a.txt")},
        file_contents={"1": b"a"},
    )
    # first index: start=0 -> window is years -> full crawl, events untouched
    _, mode = _run(connector, 0, _NOW)
    assert mode == BoxTraversalMode.FULL
    assert fake.events.calls == []
    assert fake.folders.listing_calls != []


def test_folder_scoped_connector_uses_full_crawl_not_events() -> None:
    connector, fake = _make_events_connector(
        event_pages=[make_events_page(["1"], next_stream_position=None)],
        files_by_id={"1": _file_with_parent("1", "a.txt")},
        file_contents={"1": b"a"},
    )
    connector.entry_folder_ids = ["200"]  # scoped -> events can't scope to subtree
    _, mode = _run(connector, _HOUR_AGO, _NOW)
    assert mode == BoxTraversalMode.FULL
    assert fake.events.calls == []


def test_slim_retrieval_never_uses_events() -> None:
    connector, fake = _make_events_connector(
        event_pages=[make_events_page(["1"], next_stream_position=None)],
        files_by_id={"1": _file_with_parent("1", "a.txt")},
        file_contents={"1": b"a"},
    )
    # slim (pruning/perm-sync) must enumerate the whole corpus, never the delta
    for _ in connector.retrieve_all_slim_docs(start=_HOUR_AGO, end=_NOW):
        pass
    assert fake.events.calls == []
    assert fake.folders.listing_calls != []
