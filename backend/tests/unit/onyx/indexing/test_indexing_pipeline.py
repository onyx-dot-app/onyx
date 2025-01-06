from typing import List

from onyx.configs.app_configs import MAX_DOCUMENT_CHARS
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import Section
from onyx.indexing.indexing_pipeline import filter_documents


def create_test_document(
    doc_id: str = "test_id",
    title: str | None = "Test Title",
    semantic_id: str = "test_semantic_id",
    sections: List[Section] | None = None,
) -> Document:
    if sections is None:
        sections = [Section(text="Test content", link="test_link")]
    return Document(
        id=doc_id,
        title=title,
        semantic_identifier=semantic_id,
        sections=sections,
        source=DocumentSource.FILE,
        metadata={},
    )


def test_filter_documents_empty_title_and_content() -> None:
    doc = create_test_document(
        title="", semantic_id="", sections=[Section(text="", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 0


def test_filter_documents_empty_title_with_content() -> None:
    doc = create_test_document(
        title="", sections=[Section(text="Valid content", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].id == "test_id"


def test_filter_documents_empty_content_with_title() -> None:
    doc = create_test_document(
        title="Valid Title", sections=[Section(text="", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].id == "test_id"


def test_filter_documents_exceeding_max_chars() -> None:
    if not MAX_DOCUMENT_CHARS:  # Skip if no max chars configured
        return
    long_text = "a" * (MAX_DOCUMENT_CHARS + 1)
    doc = create_test_document(sections=[Section(text=long_text, link="test_link")])
    result = filter_documents([doc])
    assert len(result) == 0


def test_filter_documents_valid_document() -> None:
    doc = create_test_document(
        title="Valid Title", sections=[Section(text="Valid content", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].id == "test_id"
    assert result[0].title == "Valid Title"


def test_filter_documents_whitespace_only() -> None:
    doc = create_test_document(
        title="   ", semantic_id="  ", sections=[Section(text="   ", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 0


def test_filter_documents_semantic_id_no_title() -> None:
    doc = create_test_document(
        title=None,
        semantic_id="Valid Semantic ID",
        sections=[Section(text="Valid content", link="test_link")],
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].semantic_identifier == "Valid Semantic ID"


def test_filter_documents_multiple_sections() -> None:
    doc = create_test_document(
        sections=[
            Section(text="Content 1", link="test_link"),
            Section(text="Content 2", link="test_link"),
            Section(text="Content 3", link="test_link"),
        ]
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert len(result[0].sections) == 3


def test_filter_documents_multiple_documents() -> None:
    docs = [
        create_test_document(doc_id="1", title="Title 1"),
        create_test_document(
            doc_id="2", title="", sections=[Section(text="", link="test_link")]
        ),  # Should be filtered
        create_test_document(doc_id="3", title="Title 3"),
    ]
    result = filter_documents(docs)
    assert len(result) == 2
    assert {doc.id for doc in result} == {"1", "3"}


def test_filter_documents_empty_batch() -> None:
    result = filter_documents([])
    assert len(result) == 0
