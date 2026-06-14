"""GoogleDriveConnector converts retrieved files to documents in bounded
sub-batches. The connector must hold only a sub-batch of files and their
converted documents at a time — not the whole drive — so peak memory stays
flat regardless of drive size."""

from collections.abc import Callable
from collections.abc import Iterator
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
from onyx.connectors.google_drive.models import RetrievedDriveFile
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.utils.threadpool_concurrency import ThreadSafeDict

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


def _make_file(idx: int) -> RetrievedDriveFile:
    rf = MagicMock(spec=RetrievedDriveFile)
    rf.error = None
    rf.drive_file = {"id": f"file_{idx}", "name": f"file_{idx}"}
    return rf


def _parallel_stub(calls: list[int]) -> Callable[..., list]:
    """Replacement for run_functions_tuples_in_parallel that records each call's
    size and returns one stub Document per file without running real conversion."""

    def _run(func_with_args: list, **_kwargs: object) -> list:
        calls.append(len(func_with_args))
        return [MagicMock(spec=Document) for _ in func_with_args]

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
        return [MagicMock(spec=HierarchyNode)]

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
