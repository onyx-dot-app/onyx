"""Fewer permission reads against the mock server: the listing asks the delta
which files have permissions of their own, and conversion reads permissions
only for those files. A file that inherits gets the access of its parent."""

import time

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.microsoft_utils import drive_delta
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    ResolveTarget,
    SlimDocumentStub,
)
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.listing import (
    SharepointListedKind,
    SharepointListingPayload,
)
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
    list_stubs,
)

pytestmark = pytest.mark.usefixtures("ee_permission_sync")

# A corpus where a part of the files and folders have permissions of their own.
_CORPUS = {
    "num_sites": 2,
    "libraries_per_site": 1,
    "folder_depth": 2,
    "folder_branching": 2,
    "files_per_folder": 6,
    "pages_per_site": 1,
    "unique_permission_fraction": 0.2,
}


def _file_payloads(
    stubs: list[SlimDocumentStub],
) -> dict[str, SharepointListingPayload]:
    payloads: dict[str, SharepointListingPayload] = {}
    for stub in stubs:
        assert stub.listing_payload is not None
        payload = stub.listing_payload.as_type(SharepointListingPayload)
        if payload.kind == SharepointListedKind.DRIVE_ITEM:
            payloads[stub.id] = payload
    return payloads


def _convert(
    connector: SharepointConnector, stubs: list[SlimDocumentStub]
) -> dict[str, ExternalAccess | None]:
    converted = list(
        connector.resolve_targets(
            [
                ResolveTarget(document_id=stub.id, listing_payload=stub.listing_payload)
                for stub in stubs
            ],
            include_permissions=True,
        )
    )
    failures = [item for item in converted if isinstance(item, ConnectorFailure)]
    assert not failures, failures[0].failure_message
    return {
        item.id: item.external_access
        for item in converted
        if isinstance(item, Document)
    }


def _expected_access(mock: MockSharepoint) -> dict[str, ExternalAccess]:
    expected: dict[str, ExternalAccess] = {}
    described = [mock.describe_file(file_id) for file_id in mock.supported_file_ids()]
    described += [mock.describe_page(page_id) for page_id in mock.page_ids()]
    ids = list(mock.supported_file_ids()) + list(mock.page_ids())
    for document_id, item in zip(ids, described, strict=True):
        effective = item["effective_access"]
        expected[document_id] = ExternalAccess(
            external_user_emails=set(effective["user_emails"]),
            external_user_group_ids=set(effective["group_ids"]),
            is_public=effective["is_public"],
        )
    return expected


def test_an_inherited_file_gets_the_access_of_a_read_of_its_own(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    end = time.time()
    # Today's reads: one for each file, on the fetching path.
    fetched = {
        document.id: document.external_access
        for document in load_all_from_connector(
            mock.build_connector(certificate=True), 0, end, include_permissions=True
        ).documents
    }
    per_file_reads = mock.op_count("rest.role_assignments")
    mock.reset_stats()

    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, end=end, include_permissions=True)
    assert not listing.failures
    payloads = _file_payloads(listing.stubs)
    unique = set(mock.summary()["unique_permission_item_ids"])
    inherits = {file_id for file_id, p in payloads.items() if p.inherits_permissions}
    # The listing marks exactly the files with no permissions of their own.
    assert inherits == set(payloads) - unique
    assert inherits and set(payloads) & unique
    # It reads the delta of each drive, and not the folders one by one.
    assert "graph.drive.children" not in mock.stats()["ops"]
    listing_reads = mock.op_count("rest.role_assignments")

    converted = _convert(connector, listing.stubs)

    assert converted == fetched == _expected_access(mock)
    conversion_reads = mock.op_count("rest.role_assignments") - listing_reads
    own_reads = len(set(payloads) & unique) + len(mock.page_ids())
    parents = len(mock.summary()["folder_ids"]) + len(mock.drive_ids())
    # One read for each file with its own permissions and each page, and at
    # most one for each folder or library that holds a file that inherits.
    assert own_reads <= conversion_reads <= own_reads + parents
    assert listing_reads + conversion_reads < per_file_reads


def test_with_no_answer_from_graph_each_file_gets_its_own_read(
    own_mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed: when Graph does not say that it applied the preference,
    the listing does not trust a missing `shared` facet."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    monkeypatch.setattr(
        drive_delta, "parse_applied_preferences", lambda _headers: frozenset()
    )

    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, include_permissions=True)
    payloads = _file_payloads(listing.stubs)
    assert payloads and not any(p.inherits_permissions for p in payloads.values())
    mock.reset_stats()

    converted = _convert(connector, listing.stubs)

    assert converted == _expected_access(mock)
    assert mock.op_count("rest.role_assignments") == len(listing.stubs)


def test_sharing_links_as_public_keeps_a_read_for_each_file(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """A file's sharing links are read for each file, so the listing does not
    mark a file as one that inherits."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS | {"sharing_link_fraction": 0.3})

    connector = mock.build_connector(
        certificate=True, treat_sharing_link_as_public=True
    )
    listing = list_stubs(connector, include_permissions=True)

    payloads = _file_payloads(listing.stubs)
    assert payloads and not any(p.inherits_permissions for p in payloads.values())


def test_a_change_of_a_folders_permissions_reaches_its_files(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """A second listing run does not use the access that the first run read
    for the folder, in Redis or in the connector object, so a file whose
    folder gets new permissions gets them."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS | {"unique_permission_fraction": 0.0})
    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, include_permissions=True)
    assert _convert(connector, listing.stubs) == _expected_access(mock)

    folder_id = mock.summary()["folder_ids"][0]
    user = mock.summary()["user_emails"][0]
    mock.set_permissions(
        item_id=folder_id,
        inherit=False,
        grants=[{"principal": {"kind": "user", "key": user}, "role": "read"}],
    )
    # The same connector object, as a conversion worker keeps it.
    listing = list_stubs(connector, include_permissions=True)

    assert _convert(connector, listing.stubs) == _expected_access(mock)


def test_a_delta_link_from_a_full_pass_marks_no_file(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """A full pass with no permission sync takes a delta cursor that does not
    ask for the `shared` facet. When its checkpoint continues with permission
    sync, a file with no facet is not marked as one that inherits."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    connector = mock.build_connector(certificate=True)
    end = time.time()
    checkpoint = connector.build_dummy_checkpoint()
    # Without permission sync, until the walk of the first drive is over and
    # the delta from its cursor is next.
    for _ in range(1_000):
        step = connector.retrieve_slim_docs_from_checkpoint(0, end, checkpoint, False)
        while True:
            try:
                next(step)
            except StopIteration as stop:
                checkpoint = stop.value
                break
        if checkpoint.full_pass_catching_up:
            break
    assert checkpoint.full_pass_catching_up
    # A file changes, so the delta from the cursor has an item.
    changed = min(
        file_id
        for file_id in mock.supported_file_ids()
        if mock.describe_file(file_id)["file"]["drive_id"]
        == (checkpoint.current_drive.drive_id if checkpoint.current_drive else "")
    )
    mock.touch([changed])

    step = connector.retrieve_slim_docs_from_checkpoint(0, end, checkpoint, True)
    stubs = [item for item in step if isinstance(item, SlimDocumentStub)]

    assert [stub.id for stub in stubs] == [changed]
    assert not _file_payloads(stubs)[changed].inherits_permissions


def test_a_resync_marks_no_file(own_mock_sharepoint: MockSharepoint) -> None:
    """After a 410, Graph gives the URL of the new delta. The listing does
    not know that it asks for the `shared` facet."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    mock.patch_config({"faults": {"expire_delta_tokens": True}})

    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, start=time.time() - 3600, include_permissions=True)

    payloads = _file_payloads(listing.stubs)
    assert not any(p.inherits_permissions for p in payloads.values())


@pytest.mark.parametrize("parent_path", [None, "/drives/unknown"])
def test_a_file_with_no_known_parent_gets_its_own_read(
    own_mock_sharepoint: MockSharepoint, parent_path: str | None
) -> None:
    """A file that inherits, but whose parent the listing cannot name, never
    takes the library's access: it gets a permission read of its own."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, include_permissions=True)
    changed: list[str] = []
    for file_id, payload in _file_payloads(listing.stubs).items():
        if payload.inherits_permissions:
            payload.parent_path = parent_path
            changed.append(file_id)
    assert changed
    mock.reset_stats()

    converted = _convert(connector, listing.stubs)

    expected = _expected_access(mock)
    assert {doc_id: converted[doc_id] for doc_id in changed} == {
        doc_id: expected[doc_id] for doc_id in changed
    }
    assert mock.op_count("rest.role_assignments") >= len(changed)
