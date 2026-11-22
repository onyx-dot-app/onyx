"""The Drive checkpointed slim listing against the mock Google Drive server.

The resume test runs one connector call at a time and sends the checkpoint
through JSON between calls, as docfetching does. The union of the stubs must be
the full corpus with no duplicates."""

import re
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from onyx.connectors.google_drive import parallel_listing
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import (
    DriveListingPayload,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
)
from onyx.connectors.google_drive.source_operations import GoogleDriveHttpError
from onyx.connectors.models import (
    ConnectorFailure,
    HierarchyNode,
    SlimDocument,
    SlimDocumentStub,
)
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive

_FILE_ID_PATTERN = re.compile(r"/(?:d|folders)/([A-Za-z0-9_-]+)")
_MAX_CALLS = 1000


class _Listing:
    def __init__(self) -> None:
        self.stubs: list[SlimDocumentStub] = []
        self.nodes: list[HierarchyNode] = []
        self.failures: list[ConnectorFailure] = []
        # The checkpoint each call returned, after its trip through JSON.
        self.checkpoints: list[GoogleDriveCheckpoint] = []
        self.calls = 0
        self.failed_calls = 0

    @property
    def file_ids(self) -> list[str]:
        return [_file_id(stub.id) for stub in self.stubs]


def _file_id(document_id: str) -> str:
    match = _FILE_ID_PATTERN.search(document_id)
    return match.group(1) if match else document_id


def list_with_resume(
    connector: GoogleDriveConnector,
    include_permissions: bool = False,
    after_call: Callable[["_Listing"], None] | None = None,
    retry_failed_calls: bool = False,
    start: float = 0,
) -> _Listing:
    """Runs the listing to its end, one call at a time.

    With ``retry_failed_calls``, a call that raises runs again from the
    checkpoint it started with, as the next index attempt does. The test
    drops what the failed call yielded: docfetching stores it, and the
    second run of the call upserts the same document ids."""
    listing = _Listing()
    end = time.time()
    checkpoint = connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        listing.calls += 1
        if listing.calls > _MAX_CALLS:
            raise AssertionError("The listing did not finish")
        generator = connector.retrieve_slim_docs_from_checkpoint(
            start, end, checkpoint, include_permissions
        )
        items: list[SlimDocument | HierarchyNode | ConnectorFailure] = []
        try:
            while True:
                try:
                    items.append(next(generator))
                except StopIteration as stop:
                    next_checkpoint = stop.value
                    break
        except GoogleDriveHttpError:
            if not retry_failed_calls:
                raise
            listing.failed_calls += 1
            continue
        for item in items:
            if isinstance(item, SlimDocumentStub):
                listing.stubs.append(item)
            elif isinstance(item, HierarchyNode):
                listing.nodes.append(item)
            elif isinstance(item, ConnectorFailure):
                listing.failures.append(item)
            else:
                raise AssertionError("The indexing listing must yield stubs")
        # Docfetching stores the checkpoint as JSON between connector calls.
        checkpoint = connector.validate_checkpoint_json(
            next_checkpoint.model_dump_json()
        )
        listing.checkpoints.append(checkpoint)
        if after_call is not None:
            after_call(listing)
    return listing


@pytest.fixture
def listing_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Small pages and a small budget, so the small corpus needs many calls."""
    monkeypatch.setattr(parallel_listing, "LISTING_PAGE_SIZE", 5)
    monkeypatch.setattr(parallel_listing, "CALL_BUDGET_FILES", 10)


@pytest.mark.usefixtures("listing_mode")
def test_resumed_listing_is_the_full_corpus_with_no_duplicates(
    mock_drive: MockDrive,
) -> None:
    expected = mock_drive.content_file_ids()
    assert expected

    listing = list_with_resume(mock_drive.build_connector())

    assert listing.failures == []
    # More than one call, so the test did resume from a JSON checkpoint.
    assert listing.calls > 1
    assert len(listing.file_ids) == len(set(listing.file_ids)), "duplicate stubs"
    assert set(listing.file_ids) == expected
    assert listing.nodes, "the listing yields hierarchy nodes"

    for stub in listing.stubs:
        assert stub.mime_type
        assert stub.doc_updated_at is not None
        assert isinstance(stub.listing_payload, DriveListingPayload)
        assert stub.listing_payload.retriever_email
        # Permission sync is off, so the stub has no access data.
        assert stub.external_access is None


def test_stub_goes_through_json_with_its_payload(mock_drive: MockDrive) -> None:
    listing = list_with_resume(mock_drive.build_connector())
    stub = listing.stubs[0]

    dumped = stub.model_dump(mode="json")

    payload = stub.listing_payload
    assert isinstance(payload, DriveListingPayload)
    assert payload.drive_file is not None
    assert DriveListingPayload.model_validate(dumped["listing_payload"]) == payload
    assert dumped["mime_type"] == stub.mime_type
    # Pruning and permission sync read a stub as a slim document.
    assert SlimDocument.model_validate(dumped).id == stub.id
    # A later step loads the stub and reads the payload as the Drive type.
    loaded = SlimDocumentStub.model_validate_json(stub.model_dump_json())
    assert loaded.listing_payload is not None
    payload = loaded.listing_payload.as_type(DriveListingPayload)
    assert payload.retriever_email == dumped["listing_payload"]["retriever_email"]


@pytest.mark.usefixtures("listing_mode")
def test_listing_applies_the_size_threshold(mock_drive: MockDrive) -> None:
    full = list_with_resume(mock_drive.build_connector())
    sizes = sorted(s.size_bytes for s in full.stubs if s.size_bytes is not None)
    assert len(sizes) > 1, "the mock corpus has uploaded files with a size"
    threshold = sizes[len(sizes) // 2]

    connector = mock_drive.build_connector()
    connector.size_threshold = threshold
    filtered = list_with_resume(connector)

    too_large = {s.id for s in full.stubs if (s.size_bytes or 0) > threshold}
    assert too_large
    assert {s.id for s in filtered.stubs} == {s.id for s in full.stubs} - too_large


def _pruning_ids(connector: GoogleDriveConnector) -> set[str]:
    return {
        doc.id
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    }


def test_pruning_omits_files_that_indexing_skips(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pruning deletes what its listing lacks, so it must lack exactly the
    files that indexing skips."""
    full = list_with_resume(mock_drive.build_connector())
    all_ids = {stub.id for stub in full.stubs}
    sizes = sorted(s.size_bytes for s in full.stubs if s.size_bytes is not None)
    assert len(sizes) > 1, "the mock corpus has uploaded files with a size"
    threshold = sizes[len(sizes) // 2]
    too_large = {s.id for s in full.stubs if (s.size_bytes or 0) > threshold}
    assert too_large

    # The mock corpus has no images, so the listing reports some files as images.
    small = sorted(s.id for s in full.stubs if s.id not in too_large)
    images = set(small[:3])
    image_file_ids = {_file_id(doc_id) for doc_id in images}
    fetch_drive_items = GoogleDriveConnector._fetch_drive_items

    def _fetch_with_images(
        self: GoogleDriveConnector, *args: Any, **kwargs: Any
    ) -> Iterator[RetrievedDriveFile]:
        for retrieved in fetch_drive_items(self, *args, **kwargs):
            if retrieved.drive_file.get("id") in image_file_ids:
                retrieved.drive_file["mimeType"] = "image/png"
            yield retrieved

    monkeypatch.setattr(GoogleDriveConnector, "_fetch_drive_items", _fetch_with_images)

    connector = mock_drive.build_connector()
    connector.size_threshold = threshold
    assert _pruning_ids(connector) == all_ids - too_large - images

    connector.set_allow_images(True)
    assert _pruning_ids(connector) == all_ids - too_large
