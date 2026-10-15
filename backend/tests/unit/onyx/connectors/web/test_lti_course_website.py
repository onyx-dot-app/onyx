from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import TextSection
from onyx.connectors.web.connector import ScrapeResult
from onyx.connectors.web.connector import WebConnector


def _load_page(url: str, course_id: str | None) -> list[Document | HierarchyNode]:
    connector = WebConnector(
        base_url=url,
        web_connector_type="single",
        lti_context_id=course_id,
    )
    result = ScrapeResult()
    result.doc = Document(
        id=url,
        source=DocumentSource.WEB,
        semantic_identifier="Course page",
        sections=[TextSection(link=url, text="Course content")],
        metadata={},
    )

    with (
        patch("onyx.connectors.web.connector.check_internet_connection"),
        patch("onyx.connectors.web.connector.ScrapeSessionContext.initialize"),
        patch("onyx.connectors.web.connector.ScrapeSessionContext.stop"),
        patch.object(connector, "_do_scrape", return_value=result),
    ):
        return [item for batch in connector.load_from_state() for item in batch]


def test_lti_website_has_selectable_node_and_course_scoped_document() -> None:
    url = "https://example.edu/course"
    emitted = _load_page(url, "course-1")

    nodes = [item for item in emitted if isinstance(item, HierarchyNode)]
    documents = [item for item in emitted if isinstance(item, Document)]
    assert len(nodes) == 1
    assert nodes[0].link == url
    assert len(documents) == 1
    assert documents[0].parent_hierarchy_raw_node_id == nodes[0].raw_node_id
    assert documents[0].id != url


def test_same_website_in_different_courses_has_distinct_documents() -> None:
    url = "https://example.edu/course"
    first_course = _load_page(url, "course-1")
    second_course = _load_page(url, "course-2")

    first_doc = next(item for item in first_course if isinstance(item, Document))
    second_doc = next(item for item in second_course if isinstance(item, Document))
    assert first_doc.id != second_doc.id
    assert (
        first_doc.parent_hierarchy_raw_node_id
        != second_doc.parent_hierarchy_raw_node_id
    )


def test_regular_web_connector_keeps_existing_document_identity() -> None:
    url = "https://example.edu/course"
    emitted = _load_page(url, None)

    assert not any(isinstance(item, HierarchyNode) for item in emitted)
    document = next(item for item in emitted if isinstance(item, Document))
    assert document.id == url
    assert document.parent_hierarchy_raw_node_id is None
