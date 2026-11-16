"""Converting Drive files from their listing payload gives the same
documents as today's checkpointed load, with no files.get calls."""

import time
from collections.abc import Iterator
from typing import Any

import pytest

from onyx.connectors.google_drive import connector as connector_module
from onyx.connectors.google_drive import doc_conversion, parallel_listing
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import (
    DriveListingPayload,
    GoogleDriveCheckpoint,
    RetrievedDriveFile,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    ResolveTarget,
    SlimDocument,
    SlimDocumentStub,
)
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.connectors.google_drive.test_checkpointed_slim_listing import (  # noqa: E501
    list_with_resume,
    listing_mode,  # noqa: F401
)


def _summary(docs: list[Document]) -> dict[str, tuple[str, Any, int]]:
    return {
        doc.id: (
            doc.semantic_identifier,
            (doc.doc_metadata or {}).get("hierarchy", {}).get("source_path"),
            len(doc.sections),
        )
        for doc in docs
    }


def _load_documents(mock_drive: MockDrive) -> list[Document]:
    """Today's path: the checkpointed full load."""
    connector = mock_drive.build_connector()
    checkpoint = connector.build_dummy_checkpoint()
    docs: list[Document] = []
    end = time.time()
    while checkpoint.has_more:
        generator = connector.load_from_checkpoint(0, end, checkpoint)
        while True:
            try:
                item = next(generator)
            except StopIteration as stop:
                checkpoint = stop.value
                break
            if isinstance(item, Document):
                docs.append(item)
    return docs


def _files_get_calls(mock_drive: MockDrive) -> int:
    ops = mock_drive.stats()["ops"]
    return int(ops.get("drive.files.get", {}).get("count", 0))


@pytest.fixture
def one_listing_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """The listing lists one page at a time, as the inline load does.

    A non-organizer lists a shared drive, so that listing is not exact. A
    file in that drive that is also shared with the admin is then claimed
    by the first of the two listings to reach it. The admin cannot see the
    file's folder, so the admin's copy has no parent and the file's path
    changes with that order. With one worker the order is fixed, and both
    runs list the file as the same user."""
    monkeypatch.setattr(parallel_listing, "ADAPTIVE_MAX_WORKERS", 1)


@pytest.mark.usefixtures("listing_mode", "one_listing_worker")
def test_payload_conversion_matches_reindex(mock_drive: MockDrive) -> None:
    connector = mock_drive.build_connector()
    listing = list_with_resume(connector)
    assert listing.stubs

    targets: list[ResolveTarget] = []
    for stub in listing.stubs:
        assert stub.listing_payload is not None
        # The stub batch store keeps the payload as JSON.
        payload = DriveListingPayload.model_validate(
            stub.listing_payload.model_dump(mode="json")
        )
        targets.append(ResolveTarget(document_id=stub.id, listing_payload=payload))

    doc_conversion._folder_cache.clear()
    mock_drive.reset_stats()
    from_payload = list(connector.resolve_targets(targets))
    # The listing returned each folder, so each stub has its folder path.
    assert all(
        isinstance(t.listing_payload, DriveListingPayload)
        and t.listing_payload.folder_path
        for t in targets
    )
    assert _files_get_calls(mock_drive) == 0

    doc_conversion._folder_cache.clear()
    today = _load_documents(mock_drive)

    assert today
    assert any(path for _, path, _ in _summary(today).values())
    assert not [r for r in from_payload if isinstance(r, ConnectorFailure)]
    assert _summary([d for d in from_payload if isinstance(d, Document)]) == _summary(
        today
    )


def test_shared_drive_stubs_name_the_drive_members_as_readers(
    mock_drive: MockDrive,
) -> None:
    """Any member of a shared drive can read its files. The stub names them,
    so conversion can spread its reads over them."""
    listing = list_with_resume(mock_drive.build_connector())
    state = listing.checkpoints[-1].listing
    assert state is not None
    assert any(state.drive_member_emails.values())

    checked = 0
    for stub in listing.stubs:
        payload = stub.listing_payload
        assert isinstance(payload, DriveListingPayload)
        drive_id = (payload.drive_file or {}).get("driveId")
        members = state.drive_member_emails.get(drive_id, []) if drive_id else []
        others = {m for m in members if m.lower() != payload.retriever_email.lower()}
        if others:
            checked += 1
            assert others <= set(payload.reader_emails)
            assert payload.retriever_email not in payload.reader_emails
    assert checked > 0


# A file of this shared drive is also shared with the admin, who is not a
# member of the drive and cannot read its name.
_SHARED_FILE_NAME = "Incident Quarterly 14"


class _NonMemberFirst:
    """A finished listing of the mock corpus, and the files of the drive
    that holds _SHARED_FILE_NAME. The shared file comes first, listed as the
    admin, as when the admin's listing claims it before the drive's."""

    def __init__(self, mock_drive: MockDrive) -> None:
        self.connector = mock_drive.build_connector()
        listing = list_with_resume(self.connector)
        payloads = [
            DriveListingPayload.model_validate(
                stub.listing_payload.model_dump(mode="json")
            )
            for stub in listing.stubs
            if stub.listing_payload is not None
        ]
        shared = next(
            p for p in payloads if (p.drive_file or {}).get("name") == _SHARED_FILE_NAME
        )
        assert shared.drive_file is not None
        self.drive_id: str = shared.drive_file["driveId"]
        admin = self.connector.primary_admin_email
        ops = self.connector.ops
        assert (
            ops.get_shared_drive_name(user_email=admin, drive_id=self.drive_id) is None
        )

        self.checkpoint: GoogleDriveCheckpoint = listing.checkpoints[-1].model_copy(
            deep=True
        )
        assert self.checkpoint.listing is not None
        self.checkpoint.listing.drive_names = {}
        organizer = self.checkpoint.organizer_email_by_drive_id[self.drive_id]
        real_name = ops.get_shared_drive_name(
            user_email=organizer, drive_id=self.drive_id
        )
        assert real_name
        self.real_name: str = real_name

        others = [
            RetrievedDriveFile(drive_file=p.drive_file, user_email=p.retriever_email)
            for p in payloads
            if p.drive_file is not None
            and p.drive_file.get("driveId") == self.drive_id
            and p is not shared
        ]
        assert others
        self.files = [
            RetrievedDriveFile(drive_file=shared.drive_file, user_email=admin),
            *others,
        ]

    def fetch(self, *_args: Any, **_kwargs: Any) -> Iterator[RetrievedDriveFile]:
        yield from self.files


@pytest.mark.usefixtures("listing_mode")
def test_non_member_listing_first_keeps_the_drive_name_in_stub_paths(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The listing reads the drive name as a user who can see the drive, and
    never caches the fallback name."""
    case = _NonMemberFirst(mock_drive)
    connector = case.connector
    listing_state = case.checkpoint.listing
    monkeypatch.setattr(connector, "_plan_listing", lambda *_a, **_k: listing_state)
    monkeypatch.setattr(connector, "_fetch_drive_items", case.fetch)
    monkeypatch.setattr(
        GoogleDriveConnector, "_resolve_unlisted_parents", lambda *_a, **_k: iter([])
    )

    failures: list[ConnectorFailure] = []
    stubs: list[SlimDocumentStub] = []
    batch: list[SlimDocument | HierarchyNode]
    for batch in connector._extract_slim_docs_from_google_drive(
        case.checkpoint, include_permissions=False, stub_failures=failures
    ):
        stubs.extend(item for item in batch if isinstance(item, SlimDocumentStub))

    assert not failures
    assert len(stubs) == len(case.files)
    for stub in stubs:
        payload = stub.listing_payload
        assert isinstance(payload, DriveListingPayload)
        assert payload.folder_path is not None
        assert payload.folder_path[0] == case.real_name, stub.id
    assert listing_state is not None
    assert listing_state.drive_names == {case.drive_id: case.real_name}


@pytest.mark.usefixtures("listing_mode")
def test_non_member_conversion_first_keeps_the_drive_name_inline(
    mock_drive: MockDrive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The inline load reads the drive name as a user who can see the drive,
    and never caches the fallback name."""
    case = _NonMemberFirst(mock_drive)
    assert case.checkpoint.listing is not None
    # One conversion at a time, so the admin's file converts first.
    monkeypatch.setattr(connector_module, "DRIVE_CONVERSION_WORKERS", 1)
    doc_conversion._folder_cache.clear()

    results = list(
        case.connector._convert_retrieved_files_to_documents(
            iter(case.files),
            case.checkpoint,
            case.checkpoint.listing,
            include_permissions=False,
        )
    )
    doc_conversion._folder_cache.clear()

    docs = [r for r in results if isinstance(r, Document)]
    assert not [r for r in results if isinstance(r, ConnectorFailure)]
    # Some files of the drive give no document (no raw file callback here).
    assert _SHARED_FILE_NAME in {doc.semantic_identifier for doc in docs}
    assert len(docs) > 1
    for doc in docs:
        path = (doc.doc_metadata or {})["hierarchy"]["source_path"]
        assert path[0] == case.real_name, doc.id
