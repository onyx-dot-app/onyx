"""Tests for BoxConnector.reindex against the real Box test corpus.

The corpus is described in README.md next to this file.
"""

from time import time
from unittest.mock import MagicMock

import pytest

from onyx.connectors.box.connector import BoxConnector
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
)
from tests.daily.connectors.box.test_box_basic import (
    EXPECTED_DOC_NAMES,
    PUBLIC_DOC_NAME,
    ROOT_DOC_NAME,
    SHARED_DOC_NAME,
    SHARED_FOLDER_NAME,
    TEST_FOLDER_NAME,
    WEB_LINK_NAME,
    _credentials,
    _find_test_folder_id,
)
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

pytestmark = pytest.mark.secrets(
    TestSecret.BOX_CLIENT_ID,
    TestSecret.BOX_CLIENT_SECRET,
    TestSecret.BOX_ENTERPRISE_ID,
    TestSecret.BOX_USER_EMAIL,
    TestSecret.BOX_COLLABORATOR_EMAIL,
)


@pytest.fixture
def box_connector(test_secrets: dict[TestSecret, str]) -> BoxConnector:
    connector = BoxConnector(
        folder_ids=[_find_test_folder_id(test_secrets)], include_web_links=True
    )
    connector.load_credentials(_credentials(test_secrets))
    return connector


@pytest.fixture
def crawled_docs(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    box_connector: BoxConnector,
) -> dict[str, Document]:
    """Crawl the small test folder once; maps semantic identifier -> doc."""
    result = load_all_from_connector(box_connector, 0, time())
    return {d.semantic_identifier: d for d in result.documents}


def _build_failures(doc_ids: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(document_id=doc_id),
            failure_message=f"Synthetic failure for {doc_id}",
        )
        for doc_id in doc_ids
    ]


def _split(
    results: list[Document | ConnectorFailure | HierarchyNode],
) -> tuple[list[Document], list[ConnectorFailure], list[HierarchyNode]]:
    return (
        [r for r in results if isinstance(r, Document)],
        [r for r in results if isinstance(r, ConnectorFailure)],
        [r for r in results if isinstance(r, HierarchyNode)],
    )


def _text_of(doc: Document) -> str:
    return " ".join(s.text for s in doc.sections if s.text).strip()


def test_reindex_single_file(
    box_connector: BoxConnector, crawled_docs: dict[str, Document]
) -> None:
    crawled = crawled_docs[SHARED_DOC_NAME]

    docs, failures, nodes = _split(
        list(box_connector.reindex(_build_failures([crawled.id])))
    )

    assert failures == []
    assert len(docs) == 1
    doc = docs[0]
    assert doc.id == crawled.id
    assert _text_of(doc) == _text_of(crawled)
    assert doc.metadata == crawled.metadata
    assert doc.parent_hierarchy_raw_node_id == crawled.parent_hierarchy_raw_node_id
    assert doc.external_access is None
    # The entry folder and the file's parent folder, linked as in the crawl.
    nodes_by_name = {n.display_name: n for n in nodes}
    assert set(nodes_by_name) == {TEST_FOLDER_NAME, SHARED_FOLDER_NAME}
    assert nodes_by_name[TEST_FOLDER_NAME].raw_parent_id is None
    assert (
        nodes_by_name[SHARED_FOLDER_NAME].raw_parent_id
        == nodes_by_name[TEST_FOLDER_NAME].raw_node_id
    )


def test_reindex_multiple_documents(
    box_connector: BoxConnector, crawled_docs: dict[str, Document]
) -> None:
    # Every file plus the web link.
    assert set(crawled_docs) == EXPECTED_DOC_NAMES | {WEB_LINK_NAME}
    target_ids = [d.id for d in crawled_docs.values()]

    docs, failures, nodes = _split(
        list(box_connector.reindex(_build_failures(target_ids)))
    )

    assert failures == []
    assert {d.id for d in docs} == set(target_ids)
    for doc in docs:
        crawled = crawled_docs[doc.semantic_identifier]
        assert doc.metadata == crawled.metadata
        assert doc.parent_hierarchy_raw_node_id == crawled.parent_hierarchy_raw_node_id
    # Each folder node is yielded once, even when several targets share it.
    node_ids = [n.raw_node_id for n in nodes]
    assert len(node_ids) == len(set(node_ids))


@pytest.mark.usefixtures("enable_ee")
def test_reindex_with_permissions(
    mock_get_unstructured_api_key: MagicMock,  # noqa: ARG001
    box_connector: BoxConnector,
    test_secrets: dict[TestSecret, str],
) -> None:
    collaborator_email = test_secrets[TestSecret.BOX_COLLABORATOR_EMAIL]
    crawl = load_all_from_connector(box_connector, 0, time(), include_permissions=True)
    crawled_by_id = {d.id: d for d in crawl.documents}
    crawled_nodes = {n.raw_node_id: n for n in crawl.hierarchy_nodes}

    docs, failures, nodes = _split(
        list(
            box_connector.reindex(
                _build_failures(list(crawled_by_id)), include_permissions=True
            )
        )
    )

    assert failures == []
    assert {d.id for d in docs} == set(crawled_by_id)
    # Access must match what the perm-sync crawl computes.
    for doc in docs:
        assert doc.external_access is not None
        assert doc.external_access == crawled_by_id[doc.id].external_access
    for node in nodes:
        assert node.external_access is not None
        assert node.external_access == crawled_nodes[node.raw_node_id].external_access

    docs_by_name = {d.semantic_identifier: d for d in docs}
    shared_access = docs_by_name[SHARED_DOC_NAME].external_access
    assert shared_access is not None
    assert collaborator_email in shared_access.external_user_emails
    root_access = docs_by_name[ROOT_DOC_NAME].external_access
    assert root_access is not None
    assert collaborator_email not in root_access.external_user_emails
    public_access = docs_by_name[PUBLIC_DOC_NAME].external_access
    assert public_access is not None
    assert public_access.is_public is True


def test_reindex_web_link_out_of_scope_when_disabled(
    test_secrets: dict[TestSecret, str], crawled_docs: dict[str, Document]
) -> None:
    connector = BoxConnector(
        folder_ids=[_find_test_folder_id(test_secrets)], include_web_links=False
    )
    connector.load_credentials(_credentials(test_secrets))
    web_link_id = crawled_docs[WEB_LINK_NAME].id

    docs, failures, _ = _split(list(connector.reindex(_build_failures([web_link_id]))))

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == web_link_id


def test_reindex_file_outside_configured_folder(
    test_secrets: dict[TestSecret, str], crawled_docs: dict[str, Document]
) -> None:
    # Scope the connector to a sibling folder; root_doc.txt is outside it.
    shared_folder_id = crawled_docs[SHARED_DOC_NAME].parent_hierarchy_raw_node_id
    assert shared_folder_id is not None
    connector = BoxConnector(folder_ids=[shared_folder_id])
    connector.load_credentials(_credentials(test_secrets))
    target = crawled_docs[ROOT_DOC_NAME].id

    docs, failures, nodes = _split(list(connector.reindex(_build_failures([target]))))

    assert docs == []
    assert nodes == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == target


@pytest.mark.parametrize("bogus", ["box-file-999999999999", "box-weblink-999999999999"])
def test_reindex_unknown_id_yields_failure(
    box_connector: BoxConnector, bogus: str
) -> None:
    docs, failures, _ = _split(list(box_connector.reindex(_build_failures([bogus]))))

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == bogus


@pytest.mark.parametrize(
    "unparseable", ["https://app.box.com/file/123", "box-file-abc", "box-folder-1"]
)
def test_reindex_unparseable_id_yields_failure(
    box_connector: BoxConnector, unparseable: str
) -> None:
    docs, failures, _ = _split(
        list(box_connector.reindex(_build_failures([unparseable])))
    )

    assert docs == []
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == unparseable


def test_reindex_bad_target_does_not_abort_others(
    box_connector: BoxConnector, crawled_docs: dict[str, Document]
) -> None:
    good = crawled_docs[ROOT_DOC_NAME].id
    bogus = "box-file-999999999999"

    docs, failures, _ = _split(
        list(box_connector.reindex(_build_failures([bogus, good])))
    )

    assert [d.id for d in docs] == [good]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == bogus


def test_reindex_empty_errors(box_connector: BoxConnector) -> None:
    assert list(box_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(box_connector: BoxConnector) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="12345"),
        failure_message="folder listing failure",
    )

    assert list(box_connector.reindex([entity])) == []
