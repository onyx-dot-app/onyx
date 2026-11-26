"""Indexes the mock SharePoint corpus with the real, unchanged connector and
checks the documents, the hierarchy nodes and the access against the corpus."""

import time
from typing import Any

from ee.onyx.external_permissions.microsoft_utils.sharepoint_permissions import (
    get_sharepoint_external_groups,
)
from onyx.access.models import ExternalAccess
from onyx.connectors.load_all import load_all_from_connector
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.db.enums import HierarchyNodeType
from tests.external_dependency_unit.connectors.sharepoint.conftest import (
    MockSharepoint,
)


def _access(effective: dict[str, Any]) -> ExternalAccess:
    return ExternalAccess(
        external_user_emails=set(effective["user_emails"]),
        external_user_group_ids=set(effective["group_ids"]),
        is_public=effective["is_public"],
    )


def _expected_document_access(
    mock_sharepoint: MockSharepoint,
) -> dict[str, ExternalAccess]:
    expected: dict[str, ExternalAccess] = {}
    for file_id in mock_sharepoint.supported_file_ids():
        described = mock_sharepoint.describe_file(file_id)
        expected[file_id] = _access(described["effective_access"])
    for page_id in mock_sharepoint.page_ids():
        described = mock_sharepoint.describe_page(page_id)
        expected[page_id] = _access(described["effective_access"])
    return expected


def _expected_node_access(mock_sharepoint: MockSharepoint) -> dict[str, ExternalAccess]:
    expected: dict[str, ExternalAccess] = {}
    for site in mock_sharepoint.sites():
        expected[site["url"]] = _access(site["effective_access"])
        for drive in site["drives"]:
            expected[drive["web_url"]] = _access(drive["effective_access"])
    summary = mock_sharepoint.summary()
    for folder_id, web_url in zip(
        summary["folder_ids"], summary["folder_web_urls"], strict=True
    ):
        described = mock_sharepoint.describe_file(folder_id)
        expected[web_url] = _access(described["effective_access"])
    return expected


def _ids_of_type(
    nodes: dict[str, HierarchyNode], node_type: HierarchyNodeType
) -> set[str]:
    return {raw_id for raw_id, node in nodes.items() if node.node_type == node_type}


def test_full_run_indexes_every_file_and_page(mock_sharepoint: MockSharepoint) -> None:
    connector = mock_sharepoint.build_connector()

    output = load_all_from_connector(connector, 0, time.time())

    document_ids = [document.id for document in output.documents]
    assert len(document_ids) == len(set(document_ids))
    assert set(document_ids) == mock_sharepoint.document_ids()
    assert not set(document_ids) & mock_sharepoint.unsupported_file_ids()
    assert all(
        isinstance(section, TextSection) and section.text
        for document in output.documents
        for section in document.sections
    )

    nodes = {node.raw_node_id: node for node in output.hierarchy_nodes}
    assert len(nodes) == len(output.hierarchy_nodes)
    assert set(nodes) == mock_sharepoint.hierarchy_node_ids()
    summary = mock_sharepoint.summary()
    assert _ids_of_type(nodes, HierarchyNodeType.SITE) == set(summary["site_urls"])
    assert _ids_of_type(nodes, HierarchyNodeType.DRIVE) == set(
        summary["drive_web_urls"]
    )

    # A run with no permission sync reads no permissions.
    stats = mock_sharepoint.stats()
    assert not [op for op in stats["ops"] if op.startswith("rest.")]
    assert "graph.item.permissions" not in stats["ops"]
    assert stats["unmatched_requests"] == []
    assert set(stats["item_downloads"]) == mock_sharepoint.supported_file_ids()
    assert set(stats["item_downloads"].values()) == {1}


def test_documents_carry_the_file_metadata(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    created = own_mock_sharepoint.add_file(
        drive_id=own_mock_sharepoint.drive_ids()[0],
        folder_path="Folder 1",
        name="Release Notes.txt",
        text="The mock corpus has a release note.",
    )
    connector = own_mock_sharepoint.build_connector()
    output = load_all_from_connector(connector, 0, time.time() + 1)

    document = next(d for d in output.documents if d.id == created["file"]["id"])
    assert document.semantic_identifier == "Release Notes.txt"
    assert document.metadata == {"drive": "Shared Documents"}
    assert document.source_mime_type == "text/plain"
    assert document.parent_hierarchy_raw_node_id == (
        f"{created['drive_web_url']}/Folder%201"
    )
    section = document.sections[0]
    assert isinstance(section, TextSection)
    assert section.text == "The mock corpus has a release note."
    assert section.link == created["web_url"]


def test_perm_sync_run_gives_the_corpus_access(
    mock_sharepoint: MockSharepoint,
    ee_permission_sync: None,  # noqa: ARG001
) -> None:
    connector = mock_sharepoint.build_connector(certificate=True)

    output = load_all_from_connector(
        connector, 0, time.time(), include_permissions=True
    )

    expected = _expected_document_access(mock_sharepoint)
    actual = {document.id: document.external_access for document in output.documents}
    assert actual == expected
    # The corpus has each kind of access.
    assert any(access.is_public for access in expected.values())
    assert any(access.external_user_emails for access in expected.values())
    assert len({frozenset(a.external_user_group_ids) for a in expected.values()}) > 2

    node_access = {
        node.raw_node_id: node.external_access for node in output.hierarchy_nodes
    }
    assert node_access == _expected_node_access(mock_sharepoint)


def test_slim_perm_sync_lists_the_same_ids(
    mock_sharepoint: MockSharepoint,
    ee_permission_sync: None,  # noqa: ARG001
) -> None:
    connector = mock_sharepoint.build_connector(certificate=True)

    documents: dict[str, ExternalAccess | None] = {}
    nodes: dict[str, ExternalAccess | None] = {}
    for batch in connector.retrieve_all_slim_docs_perm_sync():
        for entry in batch:
            if isinstance(entry, HierarchyNode):
                nodes[entry.raw_node_id] = entry.external_access
            elif isinstance(entry, SlimDocument):
                documents[entry.id] = entry.external_access

    # The slim listing does not read content, so it also lists the files
    # whose type Onyx does not index.
    expected = _expected_document_access(mock_sharepoint)
    for file_id in mock_sharepoint.unsupported_file_ids():
        described = mock_sharepoint.describe_file(file_id)
        expected[file_id] = _access(described["effective_access"])
    assert documents == expected
    assert nodes == _expected_node_access(mock_sharepoint)
    assert mock_sharepoint.stats()["downloads"] == 0


def test_slim_listing_without_permissions(mock_sharepoint: MockSharepoint) -> None:
    connector = mock_sharepoint.build_connector()

    ids = {
        entry.id
        for batch in connector.retrieve_all_slim_docs()
        for entry in batch
        if isinstance(entry, SlimDocument)
    }

    assert ids == (
        mock_sharepoint.document_ids() | mock_sharepoint.unsupported_file_ids()
    )
    assert not [op for op in mock_sharepoint.stats()["ops"] if op.startswith("rest.")]


def test_reindex_fetches_a_drive_item_and_a_site_page(
    mock_sharepoint: MockSharepoint,
) -> None:
    file_id = min(mock_sharepoint.supported_file_ids())
    page_id = min(mock_sharepoint.page_ids())
    file_link = mock_sharepoint.describe_file(file_id)["web_url"]
    page_link = mock_sharepoint.describe_page(page_id)["web_url"]
    connector = mock_sharepoint.build_connector()

    results = list(
        connector.reindex(
            [
                ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=document_id, document_link=link
                    ),
                    failure_message="failed before",
                )
                for document_id, link in ((file_id, file_link), (page_id, page_link))
            ]
        )
    )

    assert not [r for r in results if isinstance(r, ConnectorFailure)]
    documents = {r.id: r for r in results if isinstance(r, Document)}
    assert set(documents) == {file_id, page_id}
    assert all(document.sections for document in documents.values())
    nodes = {r.raw_node_id for r in results if isinstance(r, HierarchyNode)}
    assert documents[file_id].parent_hierarchy_raw_node_id in nodes
    assert documents[page_id].parent_hierarchy_raw_node_id in nodes
    stats = mock_sharepoint.stats()
    assert stats["item_downloads"] == {file_id: 1}
    # The page is read one time for its metadata and one time with its canvas.
    assert stats["ops"]["graph.site.page.get"]["count"] == 2
    assert stats["ops"]["graph.site.page.get"]["canvas_expanded"] == 1


def test_folder_scope_walks_the_children(mock_sharepoint: MockSharepoint) -> None:
    site = mock_sharepoint.sites()[0]
    drive = site["drives"][0]
    connector = mock_sharepoint.build_connector(
        sites=[f"{drive['web_url']}/Folder%201"], include_site_pages=False
    )

    output = load_all_from_connector(connector, 0, time.time())

    expected = {
        file_id
        for file_id in mock_sharepoint.supported_file_ids()
        if (described := mock_sharepoint.describe_file(file_id))["file"]["drive_id"]
        == drive["id"]
        and described["path"].startswith("Folder 1/")
    }
    assert expected
    assert {document.id for document in output.documents} == expected
    stats = mock_sharepoint.stats()
    assert stats["ops"]["graph.drive.children"]["count"] > 1
    assert "graph.drive.delta" not in stats["ops"]


def test_incremental_run_indexes_only_the_changed_files(
    own_mock_sharepoint: MockSharepoint,
) -> None:
    connector = own_mock_sharepoint.build_connector(include_site_pages=False)
    load_all_from_connector(connector, 0, time.time())
    # The delta token has whole seconds.
    poll_start = float(int(time.time()) - 1)
    touched = sorted(own_mock_sharepoint.supported_file_ids())[:3]
    own_mock_sharepoint.touch(touched)
    own_mock_sharepoint.reset_stats()

    output = load_all_from_connector(connector, poll_start, time.time() + 1)

    assert {document.id for document in output.documents} == set(touched)
    assert set(own_mock_sharepoint.stats()["item_downloads"]) == set(touched)


def test_group_sync_gives_the_corpus_groups(
    mock_sharepoint: MockSharepoint,
    ee_permission_sync: None,  # noqa: ARG001
) -> None:
    connector = mock_sharepoint.build_connector(certificate=True)

    for site in mock_sharepoint.sites():
        groups = get_sharepoint_external_groups(connector.ops, site["url"])

        actual = {group.id: sorted(group.user_emails) for group in groups}
        assert actual == site["expected_external_groups"]
        assert any(actual.values())
