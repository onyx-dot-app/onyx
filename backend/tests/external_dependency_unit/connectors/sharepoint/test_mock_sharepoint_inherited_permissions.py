"""Fewer permission reads against the mock server: the stub listing reads
which files have role assignments of their own (``HasUniqueRoleAssignments``),
and conversion reads permissions only for those files. A file that inherits
gets the access of the folder, library or site it inherits from."""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.microsoft_utils.models import (
    SharepointLibraryInheritance,
    SharepointSecurable,
    SharepointSecurableKind,
)
from onyx.connectors.microsoft_utils.sharepoint_access import (
    CONTAINER_ACCESS_TTL_SECONDS,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    ResolveTarget,
    SlimDocumentStub,
)
from onyx.connectors.sharepoint import connector as connector_module
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.listing import (
    SharepointListedKind,
    SharepointListingPayload,
)
from onyx.connectors.sharepoint.source_operations import SharepointSourceOperations
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
    list_stubs,
)

pytestmark = pytest.mark.usefixtures("ee_permission_sync")

# A corpus where a part of the files and folders have role assignments of
# their own. Some of the files with their own have less access than their
# folder.
_CORPUS = {
    "num_sites": 2,
    "libraries_per_site": 1,
    "folder_depth": 2,
    "folder_branching": 2,
    "files_per_folder": 6,
    "pages_per_site": 1,
    "unique_permission_fraction": 0.2,
}
_ROLE_READS = "rest.role_assignments"


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
    ids = list(mock.supported_file_ids()) + list(mock.page_ids())
    described = [mock.describe_file(file_id) for file_id in mock.supported_file_ids()]
    described += [mock.describe_page(page_id) for page_id in mock.page_ids()]
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
    # One library and one folder have role assignments of their own, the
    # other library inherits the site's, so files inherit from a folder, a
    # library and a site.
    user = mock.summary()["user_emails"][-1]
    grants = [{"principal": {"kind": "user", "key": user}, "role": "read"}]
    mock.set_permissions(drive_id=mock.drive_ids()[0], grants=grants)
    mock.set_permissions(item_id=mock.summary()["folder_ids"][0], grants=grants)
    end = time.time()
    # Today's reads: one for each file, on the fetching path.
    fetched = {
        document.id: document.external_access
        for document in load_all_from_connector(
            mock.build_connector(certificate=True), 0, end, include_permissions=True
        ).documents
    }
    per_file_reads = mock.op_count(_ROLE_READS)
    mock.reset_stats()

    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, end=end, include_permissions=True)
    assert not listing.failures
    payloads = _file_payloads(listing.stubs)
    unique = set(mock.summary()["unique_permission_item_ids"])
    sources = {
        file_id: p.inherited_access_from
        for file_id, p in payloads.items()
        if p.inherited_access_from is not None
    }
    inherits = set(sources)
    # The listing names a source for exactly the files with none of their own.
    assert inherits == set(payloads) - unique
    assert inherits and set(payloads) & unique
    kinds = {source.kind for source in sources.values()}
    assert kinds == {
        SharepointSecurableKind.LIST_ITEM,
        SharepointSecurableKind.LIBRARY,
        SharepointSecurableKind.SITE,
    }
    # One read of the items of each library.
    assert mock.op_count("rest.list.items") == len(mock.drive_ids())
    listing_reads = mock.op_count(_ROLE_READS)

    converted = _convert(connector, listing.stubs)

    assert converted == fetched == _expected_access(mock)
    conversion_reads = mock.op_count(_ROLE_READS) - listing_reads
    assert listing_reads + conversion_reads < per_file_reads


def test_a_file_missing_from_the_read_gets_its_own_read(
    own_mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file that the read of its library does not name (a newer file, or a
    folder above it that is not in the read) reads its own permissions."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    unique = set(mock.summary()["unique_permission_item_ids"])
    original = connector_module.inherited_access_sources

    def without_files(
        library: SharepointLibraryInheritance,  # noqa: ARG001
        list_id: str,  # noqa: ARG001
    ) -> dict[int, SharepointSecurable]:
        return {}

    monkeypatch.setattr(connector_module, "inherited_access_sources", without_files)
    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, include_permissions=True)
    monkeypatch.setattr(connector_module, "inherited_access_sources", original)
    payloads = _file_payloads(listing.stubs)
    assert set(payloads) - unique
    assert not any(p.inherited_access_from for p in payloads.values())
    mock.reset_stats()

    converted = _convert(connector, listing.stubs)

    assert converted == _expected_access(mock)
    assert mock.op_count(_ROLE_READS) >= len(listing.stubs)


def test_a_failed_read_of_the_library_gives_each_file_its_own_read(
    own_mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)

    def refuse(_self: SharepointSourceOperations, **_kwargs: Any) -> None:
        raise RuntimeError("the read failed")

    monkeypatch.setattr(SharepointSourceOperations, "get_library_inheritance", refuse)
    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, include_permissions=True)

    assert not listing.failures
    payloads = _file_payloads(listing.stubs)
    assert payloads and not any(p.inherited_access_from for p in payloads.values())
    assert _convert(connector, listing.stubs) == _expected_access(mock)


def test_sharing_links_as_public_keeps_a_read_for_each_file(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """A file's sharing links are read for each file, so the listing names no
    source and does not read the library."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS | {"sharing_link_fraction": 0.3})

    connector = mock.build_connector(
        certificate=True, treat_sharing_link_as_public=True
    )
    listing = list_stubs(connector, include_permissions=True)

    payloads = _file_payloads(listing.stubs)
    assert payloads and not any(p.inherited_access_from for p in payloads.values())
    assert mock.op_count("rest.list.items") == 0


def test_a_change_of_a_folders_permissions_reaches_its_files(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """A second listing run reads the library again and does not use the
    access that the first run read, in Redis or in the connector object."""
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


def test_a_stale_read_of_the_library_gives_each_file_its_own_read(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """A file that got role assignments of its own after the listing read its
    library gets them, when conversion runs after the read is too old."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS | {"unique_permission_fraction": 0.0})
    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, include_permissions=True)
    payloads = _file_payloads(listing.stubs)
    changed = next(
        file_id for file_id, p in payloads.items() if p.inherited_access_from
    )
    user = mock.summary()["user_emails"][0]
    mock.set_permissions(
        item_id=changed,
        inherit=False,
        grants=[{"principal": {"kind": "user", "key": user}, "role": "read"}],
    )
    read_at = datetime.now(timezone.utc) - timedelta(
        seconds=CONTAINER_ACCESS_TTL_SECONDS + 60
    )
    stale = [
        stub.model_copy(
            update={
                "listing_payload": payloads[stub.id].model_copy(
                    update={"inheritance_read_at": read_at}
                )
            }
        )
        if stub.id in payloads
        else stub
        for stub in listing.stubs
    ]
    mock.reset_stats()

    converted = _convert(connector, stale)

    assert converted == _expected_access(mock)
    # A file that still inherits from the same securable keeps its access,
    # and the changed file gets its new, narrower access.
    sibling = next(
        file_id
        for file_id, p in payloads.items()
        if file_id != changed
        and p.inherited_access_from == payloads[changed].inherited_access_from
    )
    assert converted[changed] != converted[sibling]
    assert mock.op_count(_ROLE_READS) >= len(payloads)


def test_no_run_cache_gives_each_file_its_own_read(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    """Without a run cache, nothing bounds how long a container's access is
    kept, so a converting connector reads each file's own."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    listing = list_stubs(
        mock.build_connector(certificate=True), include_permissions=True
    )
    payloads = _file_payloads(listing.stubs)
    assert any(p.inherited_access_from for p in payloads.values())
    connector = mock.build_connector(certificate=True)
    connector.run_scoped_cache_factory = None
    mock.reset_stats()

    assert _convert(connector, listing.stubs) == _expected_access(mock)
    assert mock.op_count(_ROLE_READS) >= len(payloads)


def test_the_self_check_turns_inheritance_off_on_a_difference(
    own_mock_sharepoint: MockSharepoint,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When a file's own access differs from the access it inherits, the file
    gets its own, and each later file of the run reads its own."""
    mock = own_mock_sharepoint
    mock.set_corpus(_CORPUS)
    connector = mock.build_connector(certificate=True)
    listing = list_stubs(connector, include_permissions=True)
    payloads = _file_payloads(listing.stubs)
    inheriting = [
        stub
        for stub in listing.stubs
        if stub.id in payloads and payloads[stub.id].inherited_access_from
    ]
    assert len(inheriting) > 1
    wrong = ExternalAccess(
        external_user_emails={"nobody@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    monkeypatch.setattr(
        connector_module,
        "get_sharepoint_securable_external_access",
        lambda *_args, **_kwargs: wrong,
    )
    expected = _expected_access(mock)

    # The first files of a run are always checked.
    with caplog.at_level(logging.ERROR):
        first = _convert(connector, inheriting[:1])
    assert first == {inheriting[0].id: expected[inheriting[0].id]}
    assert any("differ from those" in record.message for record in caplog.records)

    mock.reset_stats()
    rest = _convert(connector, inheriting[1:])

    assert rest == {stub.id: expected[stub.id] for stub in inheriting[1:]}
    assert mock.op_count(_ROLE_READS) >= len(inheriting) - 1
