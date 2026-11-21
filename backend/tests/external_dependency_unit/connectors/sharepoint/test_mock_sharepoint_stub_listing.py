"""The SharePoint stub listing against the mock server: it lists every file
and site page that indexing keeps, and it downloads nothing."""

import base64
import json
import time
from urllib.parse import urlsplit

import pytest

from ee.onyx.utils import encryption as ee_encryption
from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    ResolveTarget,
    SlimDocumentStub,
)
from onyx.connectors.sharepoint.listing import (
    SharepointListedKind,
    SharepointListingPayload,
    fresh_download_url,
)
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
    list_stubs,
)


def test_the_listing_has_a_stub_for_each_file_and_page_and_downloads_nothing(
    mock_sharepoint: MockSharepoint,
) -> None:
    connector = mock_sharepoint.build_connector()

    listing = list_stubs(connector)

    assert not listing.failures
    stub_ids = [stub.id for stub in listing.stubs]
    assert len(stub_ids) == len(set(stub_ids))
    assert set(stub_ids) == mock_sharepoint.document_ids()
    assert not set(stub_ids) & mock_sharepoint.unsupported_file_ids()
    node_ids = [node.raw_node_id for node in listing.nodes]
    assert len(node_ids) == len(set(node_ids))
    assert set(node_ids) == mock_sharepoint.hierarchy_node_ids()

    stats = mock_sharepoint.stats()
    assert stats["item_downloads"] == {}
    assert "graph.item.content" not in stats["ops"]
    assert "download_url.get" not in stats["ops"]
    # The pages are listed with no canvas, and no page is read by itself.
    assert stats["ops"]["graph.site.pages.list"]["canvas_expanded"] == 0
    assert "graph.site.page.get" not in stats["ops"]
    assert stats["unmatched_requests"] == []

    for stub in listing.stubs:
        assert stub.listing_payload is not None
        payload = stub.listing_payload.as_type(SharepointListingPayload)
        assert "downloadUrl" not in payload.model_dump_json()
        assert "tempauth" not in payload.model_dump_json()
        if payload.kind == SharepointListedKind.SITE_PAGE:
            assert payload.site_id and payload.site_page
            assert "canvasLayout" not in payload.site_page
            assert stub.parent_hierarchy_raw_node_id == payload.site_url
            continue
        described = mock_sharepoint.describe_file(stub.id)
        assert (payload.drive_id, payload.item_id) == (
            described["file"]["drive_id"],
            stub.id,
        )
        assert payload.list_id
        assert payload.list_item_id == str(described["file"]["list_item_id"])
        assert payload.site_url == described["site_url"]
        assert payload.web_url == described["web_url"]
        assert stub.size_bytes == described["file"]["size"]
        assert stub.mime_type == described["file"]["mime_type"]
        assert stub.doc_updated_at is not None and stub.doc_created_at is not None


@pytest.mark.usefixtures("ee_permission_sync")
def test_the_listing_stores_each_download_link_encrypted(
    mock_sharepoint: MockSharepoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each file's stub keeps the download link that the listing read,
    encrypted with the deployment's key: the stored stub holds no part of
    the link. Conversion gets the link back from the stored stub."""
    keys = json.dumps({"test": base64.b64encode(b"k" * 32).decode()})
    keyring = ee_encryption.build_keyring("", keys, "test")
    monkeypatch.setattr(ee_encryption, "get_keyring", lambda: keyring)

    listing = list_stubs(mock_sharepoint.build_connector())

    files = mock_sharepoint.supported_file_ids()
    file_stubs = [stub for stub in listing.stubs if stub.id in files]
    assert {stub.id for stub in file_stubs} == files
    for stub in file_stubs:
        _assert_link_stored_encrypted(stub)


def _assert_link_stored_encrypted(stub: SlimDocumentStub) -> None:
    stored = stub.model_dump_json()
    loaded = SlimDocumentStub.model_validate_json(stored)
    assert loaded.listing_payload is not None
    payload = loaded.listing_payload.as_type(SharepointListingPayload)
    assert payload.download_url_listed_at is not None
    link = fresh_download_url(payload)
    assert link is not None
    query = urlsplit(link).query
    assert "tempauth=" in query
    for secret in (link, query, base64.b64encode(link.encode()).decode()):
        assert secret not in stored
    assert "tempauth" not in stored


def test_the_stubs_match_the_documents_of_the_fetching_path(
    mock_sharepoint: MockSharepoint,
) -> None:
    """The time and the size of a stub are those of the document that the
    fetching path makes, so that an unchanged document is not fetched again.
    Its parent is the same hierarchy node."""
    end = time.time()
    documents = {
        document.id: document
        for document in load_all_from_connector(
            mock_sharepoint.build_connector(), 0, end
        ).documents
    }

    listing = list_stubs(mock_sharepoint.build_connector(), end=end)

    assert {stub.id for stub in listing.stubs} == set(documents)
    for stub in listing.stubs:
        document = documents[stub.id]
        assert stub.doc_updated_at == document.doc_updated_at
        assert stub.size_bytes == document.source_size_bytes
        assert stub.doc_created_at == document.doc_created_at
        assert stub.parent_hierarchy_raw_node_id == (
            document.parent_hierarchy_raw_node_id
        )


def test_an_incremental_listing_has_only_the_changed_files(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    connector = own_mock_sharepoint.build_connector()
    list_stubs(connector)
    changed = sorted(own_mock_sharepoint.supported_file_ids())[:3]
    # The mock stamps a change with its clock, in whole seconds.
    since = time.time() - 1
    own_mock_sharepoint.touch(changed)

    listing = list_stubs(own_mock_sharepoint.build_connector(), start=since)

    listed_files = {
        stub.id
        for stub in listing.stubs
        if stub.listing_payload is not None
        and stub.listing_payload.as_type(SharepointListingPayload).kind
        == SharepointListedKind.DRIVE_ITEM
    }
    assert listed_files == set(changed)


def test_a_checkpoint_does_not_grow_with_the_drive(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    own_mock_sharepoint.set_corpus(
        {
            "num_sites": 1,
            "libraries_per_site": 1,
            "folder_depth": 1,
            "folder_branching": 2,
            "files_per_folder": 400,
            "pages_per_site": 1,
        }
    )
    connector = own_mock_sharepoint.build_connector()

    listing = list_stubs(connector)

    assert len(listing.stubs) > 800
    # Several delta pages, and a checkpoint that holds no document id.
    assert listing.steps > 5
    assert listing.largest_checkpoint < 4_000


def test_the_default_conversion_makes_the_documents_of_the_stubs(
    mock_sharepoint: MockSharepoint,
) -> None:
    """Before the connector converts from the payload, a stub goes through
    ``reindex``: every listed file and page still becomes a document."""
    connector = mock_sharepoint.build_connector()
    listing = list_stubs(connector)
    targets = [
        ResolveTarget(
            document_id=stub.id,
            document_link=(
                stub.listing_payload.as_type(SharepointListingPayload).web_url
                if stub.listing_payload is not None
                else None
            ),
            listing_payload=stub.listing_payload,
        )
        for stub in listing.stubs
    ]

    converted = list(connector.resolve_targets(targets))

    assert not [item for item in converted if isinstance(item, ConnectorFailure)]
    assert {
        item.id for item in converted if isinstance(item, Document)
    } == mock_sharepoint.document_ids()
