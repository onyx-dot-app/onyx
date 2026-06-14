"""Regression coverage for the Drive connector's bounded sub-batch conversion:
documents materialize at most one DRIVE_CONVERSION_BATCH_SIZE chunk at a time,
and hierarchy-deferred files wait for their ancestor node before converting."""

from collections.abc import Callable
from collections.abc import Iterator
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
from onyx.connectors.google_drive.models import RetrievedDriveFile
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.utils.threadpool_concurrency import ThreadSafeDict
from onyx.utils.threadpool_concurrency import ThreadSafeSet

_BATCH = 10
_CONN_MODULE = "onyx.connectors.google_drive.connector"


def _make_connector() -> GoogleDriveConnector:
    connector = GoogleDriveConnector(include_my_drives=True)
    connector._creds = MagicMock()
    connector._primary_admin_email = "admin@example.com"
    connector.exclude_domain_link_only = False
    connector._retrieved_folder_and_drive_ids = set()
    return connector


def _make_checkpoint() -> GoogleDriveCheckpoint:
    return GoogleDriveCheckpoint(
        retrieved_folder_and_drive_ids=set(),
        completion_stage=DriveRetrievalStage.DONE,
        completion_map=ThreadSafeDict(),
        all_retrieved_file_ids=set(),
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


def _parallel_stub(
    calls: list[int], captured_ids: list[list[str]] | None = None
) -> Callable[..., list]:
    """Replacement for run_functions_tuples_in_parallel that records each call's
    size and returns one stub Document per file without running real conversion."""

    def _run(func_with_args: list, **_kwargs: object) -> list:
        calls.append(len(func_with_args))
        docs: list[Document] = []
        ids_for_call: list[str] = []
        for _func, args in func_with_args:
            retrieved_file: RetrievedDriveFile = args[0]
            doc = MagicMock(spec=Document)
            file_id = str(retrieved_file.drive_file["id"])
            doc.id = file_id
            ids_for_call.append(file_id)
            docs.append(doc)
        if captured_ids is not None:
            captured_ids.append(ids_for_call)
        return docs

    return _run


def test_converts_in_bounded_sub_batches() -> None:
    connector = _make_connector()
    n_files = _BATCH * 4 + 3  # 43 -> expect sub-batches of 10,10,10,10,3
    call_sizes: list[int] = []

    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", _BATCH),
        patch.object(connector, "_get_new_ancestors_for_files", return_value=[]),
        patch(
            f"{_CONN_MODULE}.run_functions_tuples_in_parallel",
            side_effect=_parallel_stub(call_sizes),
        ),
    ):
        out = list(
            connector._convert_retrieved_files_to_documents(
                iter([_make_file(i) for i in range(n_files)]),
                _make_checkpoint(),
                include_permissions=False,
            )
        )

    # No sub-batch ever exceeds the cap, and the remainder is flushed.
    assert call_sizes == [_BATCH, _BATCH, _BATCH, _BATCH, 3]
    assert all(size <= _BATCH for size in call_sizes)
    # Every file becomes exactly one document; nothing dropped or duplicated.
    assert len(out) == n_files


def test_yields_incrementally_without_draining_whole_drive() -> None:
    connector = _make_connector()
    n_files = _BATCH * 5
    consumed = {"count": 0}

    def _counting_iter() -> Iterator[RetrievedDriveFile]:
        for i in range(n_files):
            consumed["count"] += 1
            yield _make_file(i)

    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", _BATCH),
        patch.object(connector, "_get_new_ancestors_for_files", return_value=[]),
        patch(
            f"{_CONN_MODULE}.run_functions_tuples_in_parallel",
            side_effect=_parallel_stub([]),
        ),
    ):
        gen = connector._convert_retrieved_files_to_documents(
            _counting_iter(), _make_checkpoint(), include_permissions=False
        )
        first = next(gen)

    # First document is produced after only one sub-batch is consumed, proving
    # the connector streams rather than buffering the entire drive first.
    assert isinstance(first, MagicMock)
    assert consumed["count"] == _BATCH
    assert consumed["count"] < n_files


def test_hierarchy_nodes_precede_documents_in_each_sub_batch() -> None:
    connector = _make_connector()
    n_files = _BATCH * 2  # two full sub-batches

    def _one_node_per_batch(**_kwargs: object) -> list[HierarchyNode]:
        return [MagicMock(spec=HierarchyNode, raw_node_id="node")]

    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", _BATCH),
        patch.object(
            connector,
            "_get_new_ancestors_for_files",
            side_effect=_one_node_per_batch,
        ),
        patch(
            f"{_CONN_MODULE}.run_functions_tuples_in_parallel",
            side_effect=_parallel_stub([]),
        ),
    ):
        out = list(
            connector._convert_retrieved_files_to_documents(
                iter([_make_file(i) for i in range(n_files)]),
                _make_checkpoint(),
                include_permissions=False,
            )
        )

    # One node + ten docs per sub-batch, node first each time.
    kinds = ["node" if isinstance(x, HierarchyNode) else "doc" for x in out]
    assert kinds == (["node"] + ["doc"] * _BATCH) * 2


def test_defers_documents_until_ancestor_available() -> None:
    connector = _make_connector()
    call_sizes: list[int] = []
    parent_id = "folder_1"
    converted_ids: list[list[str]] = []
    called = False

    def _fake_ancestors(*_args: object, **kwargs: object) -> list[HierarchyNode]:
        # First invocation: ancestors unavailable; second invocation resolves the folder.
        nonlocal called
        if not called:
            called = True
            return []
        seen_hierarchy_node_raw_ids = kwargs["seen_hierarchy_node_raw_ids"]
        assert isinstance(seen_hierarchy_node_raw_ids, ThreadSafeSet)
        seen_hierarchy_node_raw_ids.add(parent_id)
        return [MagicMock(spec=HierarchyNode, raw_node_id=parent_id)]

    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", 1),
        patch.object(
            connector, "_get_new_ancestors_for_files", side_effect=_fake_ancestors
        ),
        patch(
            f"{_CONN_MODULE}.run_functions_tuples_in_parallel",
            side_effect=_parallel_stub(call_sizes, converted_ids),
        ),
    ):
        out = list(
            connector._convert_retrieved_files_to_documents(
                iter(
                    [
                        _make_file(0, parent_id=parent_id),
                        _make_file(1, parent_id=parent_id),
                    ]
                ),
                _make_checkpoint(),
                include_permissions=False,
            )
        )

    assert call_sizes == [1, 1]
    assert isinstance(out[0], HierarchyNode)
    assert len(out) == 3
    assert converted_ids == [["file_0"], ["file_1"]]


def test_force_flush_chunks_pending_files() -> None:
    connector = _make_connector()
    n_files = _BATCH * 2 + 2  # ensures pending > batch when force-flushed
    call_sizes: list[int] = []

    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", _BATCH),
        patch.object(connector, "_get_new_ancestors_for_files", return_value=[]),
        patch(
            f"{_CONN_MODULE}.run_functions_tuples_in_parallel",
            side_effect=_parallel_stub(call_sizes),
        ),
    ):
        out = list(
            connector._convert_retrieved_files_to_documents(
                iter([_make_file(i, parent_id="folder") for i in range(n_files)]),
                _make_checkpoint(),
                include_permissions=False,
            )
        )

    # Folders that never resolve are drained at stream end in capped chunks.
    assert call_sizes == [_BATCH, _BATCH, 2]
    assert len(out) == n_files


def test_deferred_files_wait_for_their_folder_then_all_resolve() -> None:
    connector = _make_connector()
    n_files = 300  # large enough to rule out any fixed-size deferral cap
    folder = "shared_folder"
    call_sizes: list[int] = []

    # The folder node is emitted only when the LAST file is walked, so all 300
    # files defer first. None may be force-converted early; every one must wait
    # and then resolve once the folder appears (its node ahead of every doc).
    def _fake_ancestors(*_args: object, **kwargs: object) -> list[HierarchyNode]:
        files = cast("list[RetrievedDriveFile]", kwargs["files"])
        seen = cast("ThreadSafeSet[str]", kwargs["seen_hierarchy_node_raw_ids"])
        if any(f.drive_file["id"] == f"file_{n_files - 1}" for f in files):
            seen.add(folder)
            return [MagicMock(spec=HierarchyNode, raw_node_id=folder)]
        return []

    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", 10),
        patch.object(
            connector, "_get_new_ancestors_for_files", side_effect=_fake_ancestors
        ),
        patch(
            f"{_CONN_MODULE}.run_functions_tuples_in_parallel",
            side_effect=_parallel_stub(call_sizes),
        ),
    ):
        out = list(
            connector._convert_retrieved_files_to_documents(
                iter([_make_file(i, parent_id=folder) for i in range(n_files)]),
                _make_checkpoint(),
                include_permissions=False,
            )
        )

    nodes = [x for x in out if isinstance(x, HierarchyNode)]
    docs = [x for x in out if not isinstance(x, HierarchyNode)]
    assert len(docs) == n_files  # nothing dropped or orphaned by a cap
    assert len(nodes) == 1
    assert isinstance(out[0], HierarchyNode)  # folder node precedes every document
    assert all(size <= 10 for size in call_sizes)  # conversion stays chunked
    assert len(call_sizes) > 1  # even the all-at-once release converts in chunks


def test_skipped_conversions_are_dropped_not_counted() -> None:
    connector = _make_connector()
    n_files = 6

    # Conversion returns None for skipped files (e.g. empty/unsupported); those
    # must be dropped, not emitted — the batching must not assume 1 doc per file.
    def _skip_evens(func_with_args: list, **_kwargs: object) -> list:
        out: list[object] = []
        for _func, args in func_with_args:
            rf: RetrievedDriveFile = args[0]
            idx = int(str(rf.drive_file["id"]).removeprefix("file_"))
            out.append(None if idx % 2 == 0 else MagicMock(spec=Document))
        return out

    with (
        patch(f"{_CONN_MODULE}.DRIVE_CONVERSION_BATCH_SIZE", _BATCH),
        patch.object(connector, "_get_new_ancestors_for_files", return_value=[]),
        patch(
            f"{_CONN_MODULE}.run_functions_tuples_in_parallel",
            side_effect=_skip_evens,
        ),
    ):
        out = list(
            connector._convert_retrieved_files_to_documents(
                iter([_make_file(i) for i in range(n_files)]),
                _make_checkpoint(),
                include_permissions=False,
            )
        )

    assert len(out) == n_files // 2  # only odd-indexed files produced a document
