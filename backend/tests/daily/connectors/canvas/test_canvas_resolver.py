"""Tests for CanvasConnector.reindex against the live Canvas test instance."""

import time

import pytest

from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    HierarchyNode,
)
from tests.daily.connectors.utils import load_all_from_connector
from tests.utils.secret_names import TestSecret

CANVAS_BASE_URL = "https://canvas.onyx.app"
DOC_TYPES = ("page", "assignment", "announcement")

pytestmark = pytest.mark.secrets(TestSecret.CANVAS_TEACHER_ACCESS_TOKEN)


@pytest.fixture
def canvas_connector(test_secrets: dict[TestSecret, str]) -> CanvasConnector:
    connector = CanvasConnector(canvas_base_url=CANVAS_BASE_URL)
    connector.load_credentials(
        {"canvas_access_token": test_secrets[TestSecret.CANVAS_TEACHER_ACCESS_TOKEN]}
    )
    return connector


@pytest.fixture(scope="module")
def crawled_docs(test_secrets: dict[TestSecret, str]) -> dict[str, Document]:
    """One crawl per module. The test instance holds only a few courses."""
    connector = CanvasConnector(canvas_base_url=CANVAS_BASE_URL)
    connector.load_credentials(
        {"canvas_access_token": test_secrets[TestSecret.CANVAS_TEACHER_ACCESS_TOKEN]}
    )
    docs = load_all_from_connector(connector, 0, time.time()).documents
    return {doc.id: doc for doc in docs}


def _ids_by_type(crawled_docs: dict[str, Document]) -> dict[str, list[str]]:
    ids: dict[str, list[str]] = {doc_type: [] for doc_type in DOC_TYPES}
    for doc in crawled_docs.values():
        ids[str(doc.metadata["type"])].append(doc.id)
    for doc_type, doc_ids in ids.items():
        assert doc_ids, f"Canvas test instance has no {doc_type} documents"
    return ids


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
) -> tuple[list[Document], list[ConnectorFailure]]:
    docs = [r for r in results if isinstance(r, Document)]
    failures = [r for r in results if isinstance(r, ConnectorFailure)]
    return docs, failures


def test_reindex_single_document(
    canvas_connector: CanvasConnector,
    crawled_docs: dict[str, Document],
) -> None:
    target = _ids_by_type(crawled_docs)["page"][0]

    docs, failures = _split(list(canvas_connector.reindex(_build_failures([target]))))

    assert failures == []
    assert len(docs) == 1
    assert docs[0].id == target
    assert docs[0].semantic_identifier == crawled_docs[target].semantic_identifier
    assert docs[0].sections == crawled_docs[target].sections
    assert docs[0].external_access is None


def test_reindex_every_doc_type(
    canvas_connector: CanvasConnector,
    crawled_docs: dict[str, Document],
) -> None:
    targets = [
        doc_id for doc_ids in _ids_by_type(crawled_docs).values() for doc_id in doc_ids
    ]

    docs, failures = _split(list(canvas_connector.reindex(_build_failures(targets))))

    assert failures == []
    assert {doc.id for doc in docs} == set(targets)
    for doc in docs:
        crawled = crawled_docs[doc.id]
        assert doc.metadata == crawled.metadata
        assert doc.sections == crawled.sections
        assert doc.doc_updated_at == crawled.doc_updated_at


def test_reindex_unknown_item_yields_failure(
    canvas_connector: CanvasConnector,
    crawled_docs: dict[str, Document],
) -> None:
    course_id = crawled_docs[_ids_by_type(crawled_docs)["page"][0]].metadata[
        "course_id"
    ]
    bogus_ids = [
        f"canvas-page-{course_id}-999999999",
        f"canvas-assignment-{course_id}-999999999",
        f"canvas-announcement-{course_id}-999999999",
        # Course outside the connector's scope.
        "canvas-page-999999999-1",
    ]

    docs, failures = _split(list(canvas_connector.reindex(_build_failures(bogus_ids))))

    assert docs == []
    assert [
        f.failed_document.document_id for f in failures if f.failed_document
    ] == bogus_ids


def test_reindex_bad_target_does_not_block_others(
    canvas_connector: CanvasConnector,
    crawled_docs: dict[str, Document],
) -> None:
    good = _ids_by_type(crawled_docs)["assignment"][0]
    course_id = crawled_docs[good].metadata["course_id"]
    bad = f"canvas-assignment-{course_id}-999999999"

    docs, failures = _split(
        list(canvas_connector.reindex(_build_failures([bad, good])))
    )

    assert [doc.id for doc in docs] == [good]
    assert len(failures) == 1
    assert failures[0].failed_document is not None
    assert failures[0].failed_document.document_id == bad


def test_reindex_unparseable_id_yields_failure(
    canvas_connector: CanvasConnector,
) -> None:
    weird_ids = ["canvas-page-abc-1", "canvas-quiz-1-2", "https://canvas.onyx.app/x"]

    docs, failures = _split(list(canvas_connector.reindex(_build_failures(weird_ids))))

    assert docs == []
    assert [
        f.failed_document.document_id for f in failures if f.failed_document
    ] == weird_ids


def test_reindex_empty_errors(canvas_connector: CanvasConnector) -> None:
    assert list(canvas_connector.reindex([])) == []


def test_reindex_entity_failures_are_skipped(
    canvas_connector: CanvasConnector,
) -> None:
    entity = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="canvas-pages-1"),
        failure_message="retrieval failure",
    )

    assert list(canvas_connector.reindex([entity])) == []


@pytest.mark.usefixtures("enable_ee")
def test_reindex_with_permissions_matches_slim_access(
    canvas_connector: CanvasConnector,
    crawled_docs: dict[str, Document],
) -> None:
    targets = [
        doc_id for doc_ids in _ids_by_type(crawled_docs).values() for doc_id in doc_ids
    ]
    slim_access = {
        slim_doc.id: slim_doc.external_access
        for batch in canvas_connector.retrieve_all_slim_docs_perm_sync(
            start=0, end=time.time()
        )
        for slim_doc in batch
        if not isinstance(slim_doc, HierarchyNode)
    }

    docs, failures = _split(
        list(
            canvas_connector.reindex(_build_failures(targets), include_permissions=True)
        )
    )

    assert failures == []
    assert {doc.id for doc in docs} == set(targets)
    for doc in docs:
        assert doc.external_access is not None
        assert (
            doc.external_access.external_user_emails
            or doc.external_access.external_user_group_ids
        ), doc.id
        assert doc.external_access == slim_access[doc.id], doc.id
