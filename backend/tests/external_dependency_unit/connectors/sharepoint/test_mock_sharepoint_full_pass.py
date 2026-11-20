"""The full pass of the SharePoint stub listing against the mock server: the
folders of a drive are read with `/children`, several at one time, and a
delta from a cursor taken before the walk catches what the walk missed."""

import time

import pytest

from onyx.connectors.models import ConnectorStopSignal
from onyx.connectors.sharepoint import connector as sharepoint_connector
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
    list_stubs,
)
from tests.external_dependency_unit.connectors.sharepoint.test_mock_sharepoint_limiter import (
    StopAfterLimiter,
)


def test_a_full_pass_walks_the_folders_and_then_reads_the_delta(
    mock_sharepoint: MockSharepoint,
) -> None:
    listing = list_stubs(mock_sharepoint.build_connector())

    assert not listing.failures
    stub_ids = [stub.id for stub in listing.stubs]
    assert len(stub_ids) == len(set(stub_ids))
    assert set(stub_ids) == mock_sharepoint.document_ids()
    assert {node.raw_node_id for node in listing.nodes} == (
        mock_sharepoint.hierarchy_node_ids()
    )
    ops = mock_sharepoint.stats()["ops"]
    drives = len(mock_sharepoint.drive_ids())
    folders = len(mock_sharepoint.summary()["folder_ids"])
    # One children page for each drive root and each folder.
    assert ops["graph.drive.children"]["count"] == drives + folders
    # For each drive: the cursor before the walk, and the delta from it,
    # which has no change.
    assert ops["graph.drive.delta"]["count"] == 2 * drives


def test_an_incremental_run_reads_one_delta_stream_for_each_drive(
    mock_sharepoint: MockSharepoint,
) -> None:
    listing = list_stubs(mock_sharepoint.build_connector(), start=time.time() - 60)

    assert not listing.failures
    ops = mock_sharepoint.stats()["ops"]
    assert "graph.drive.children" not in ops
    assert ops["graph.drive.delta"]["count"] == len(mock_sharepoint.drive_ids())


def test_a_write_during_the_walk_is_listed(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    drive_id = own_mock_sharepoint.drive_ids()[0]
    # The file appears in the drive root after the walk read the root.
    own_mock_sharepoint.write_during_walk(
        drive_id=drive_id,
        op="children",
        after_calls=1,
        action="create",
        file={"drive_id": drive_id, "name": "Written Later.txt", "text": "late"},
    )

    listing = list_stubs(own_mock_sharepoint.build_connector())

    hook = own_mock_sharepoint.walk_hooks()[0]
    assert hook["fired"] is True and hook["error"] is None
    stub_ids = [stub.id for stub in listing.stubs]
    assert hook["result_file_id"] in stub_ids
    assert len(stub_ids) == len(set(stub_ids))
    assert set(stub_ids) == own_mock_sharepoint.document_ids()


def test_a_full_pass_resumes_from_its_checkpoint(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """Each step stores its checkpoint as JSON and loads it again, as
    docfetching does."""
    own_mock_sharepoint.set_corpus(
        {
            "num_sites": 1,
            "libraries_per_site": 1,
            "folder_depth": 3,
            "folder_branching": 4,
            "files_per_folder": 3,
            "pages_per_site": 0,
        }
    )

    listing = list_stubs(own_mock_sharepoint.build_connector())

    assert {stub.id for stub in listing.stubs} == own_mock_sharepoint.document_ids()
    folders = len(own_mock_sharepoint.summary()["folder_ids"])
    assert folders >= 80
    assert listing.largest_checkpoint < 20_000


def test_the_walk_reads_several_folders_at_one_time(
    own_mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    own_mock_sharepoint.patch_config({"latency": {"enabled": True, "list_ms": 100}})
    monkeypatch.setattr(sharepoint_connector, "SHAREPOINT_LISTING_WORKERS", 4)

    listing = list_stubs(own_mock_sharepoint.build_connector())

    assert {stub.id for stub in listing.stubs} == own_mock_sharepoint.document_ids()
    assert 2 <= own_mock_sharepoint.stats()["max_inflight"] <= 4


class _StopOnceLimiter(StopAfterLimiter):
    """Raises the stop signal on one call only. A walk that caught it as a
    failure would then go on to its end."""

    def __init__(self, call: int) -> None:
        super().__init__(call)
        self._raised = False

    def acquire(
        self,
        api: str,
        cost: int,
        user: str | None = None,
        request_count: int = 1,
        *,
        bulk: bool = False,
    ) -> None:
        if self._raised:
            return
        try:
            super().acquire(api, cost, user, request_count, bulk=bulk)
        except ConnectorStopSignal:
            self._raised = True
            raise


@pytest.mark.parametrize("call", [3, 8, 12, 20, 30])
def test_a_stop_during_a_limiter_wait_ends_the_listing(
    mock_sharepoint: MockSharepoint, call: int
) -> None:
    """A stop while a folder read waits for the limiter ends the listing. It
    is not a failure of the drive, after which the walk would go on."""
    connector = mock_sharepoint.build_connector()
    connector.set_source_api_limiter(_StopOnceLimiter(call))

    with pytest.raises(ConnectorStopSignal):
        list_stubs(connector)


def test_a_folder_deleted_during_the_walk_is_skipped(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """A folder deleted after the walk read its parent answers 404. The walk
    skips it and lists the rest of the drive, with no failure."""
    drive_id = own_mock_sharepoint.drive_ids()[0]
    children = own_mock_sharepoint.graph_get(f"/drives/{drive_id}/root/children")
    children.raise_for_status()
    folder_id = next(
        item["id"] for item in children.json()["value"] if "folder" in item
    )
    own_mock_sharepoint.write_during_walk(
        drive_id=drive_id,
        op="children",
        after_calls=1,
        action="delete",
        file_id=folder_id,
    )

    listing = list_stubs(own_mock_sharepoint.build_connector())

    hook = own_mock_sharepoint.walk_hooks()[0]
    assert hook["fired"] is True and hook["error"] is None
    assert not listing.failures
    stub_ids = [stub.id for stub in listing.stubs]
    assert len(stub_ids) == len(set(stub_ids))
    assert set(stub_ids) == own_mock_sharepoint.document_ids()
