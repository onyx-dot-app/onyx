from typing import Any
from typing import cast
from typing import List
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.configs.app_configs import MAX_DOCUMENT_CHARS
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.indexing.chunker import Chunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_pipeline import add_contextual_summaries
from onyx.indexing.indexing_pipeline import filter_documents
from onyx.indexing.indexing_pipeline import process_image_sections
from onyx.llm.constants import LlmProviderNames
from onyx.llm.model_response import Choice
from onyx.llm.model_response import Message
from onyx.llm.model_response import ModelResponse
from onyx.llm.utils import get_max_input_tokens


def create_test_document(
    doc_id: str = "test_id",
    title: str | None = "Test Title",
    semantic_id: str = "test_semantic_id",
    sections: List[TextSection] | None = None,
) -> Document:
    if sections is None:
        sections = [TextSection(text="Test content", link="test_link")]
    return Document(
        id=doc_id,
        title=title,
        semantic_identifier=semantic_id,
        sections=cast(list[TextSection | ImageSection], sections),
        source=DocumentSource.FILE,
        metadata={},
    )


def test_filter_documents_empty_title_and_content() -> None:
    doc = create_test_document(
        title="", semantic_id="", sections=[TextSection(text="", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 0


def test_filter_documents_empty_title_with_content() -> None:
    doc = create_test_document(
        title="", sections=[TextSection(text="Valid content", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].id == "test_id"


def test_filter_documents_empty_content_with_title() -> None:
    doc = create_test_document(
        title="Valid Title", sections=[TextSection(text="", link="test_link")]
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].id == "test_id"


def test_filter_documents_exceeding_max_chars() -> None:
    if not MAX_DOCUMENT_CHARS:  # Skip if no max chars configured
        return
    long_text = "a" * (MAX_DOCUMENT_CHARS + 1)
    doc = create_test_document(sections=[TextSection(text=long_text, link="test_link")])
    result = filter_documents([doc])
    assert len(result) == 0


def test_filter_documents_valid_document() -> None:
    doc = create_test_document(
        title="Valid Title",
        sections=[TextSection(text="Valid content", link="test_link")],
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].id == "test_id"
    assert result[0].title == "Valid Title"


def test_filter_documents_whitespace_only() -> None:
    doc = create_test_document(
        title="   ",
        semantic_id="  ",
        sections=[TextSection(text="   ", link="test_link")],
    )
    result = filter_documents([doc])
    assert len(result) == 0


def test_filter_documents_semantic_id_no_title() -> None:
    doc = create_test_document(
        title=None,
        semantic_id="Valid Semantic ID",
        sections=[TextSection(text="Valid content", link="test_link")],
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert result[0].semantic_identifier == "Valid Semantic ID"


def test_filter_documents_multiple_sections() -> None:
    doc = create_test_document(
        sections=[
            TextSection(text="Content 1", link="test_link"),
            TextSection(text="Content 2", link="test_link"),
            TextSection(text="Content 3", link="test_link"),
        ]
    )
    result = filter_documents([doc])
    assert len(result) == 1
    assert len(result[0].sections) == 3


def test_filter_documents_multiple_documents() -> None:
    docs = [
        create_test_document(doc_id="1", title="Title 1"),
        create_test_document(
            doc_id="2", title="", sections=[TextSection(text="", link="test_link")]
        ),  # Should be filtered
        create_test_document(doc_id="3", title="Title 3"),
    ]
    result = filter_documents(docs)
    assert len(result) == 2
    assert {doc.id for doc in result} == {"1", "3"}


def test_filter_documents_empty_batch() -> None:
    result = filter_documents([])
    assert len(result) == 0


@patch("onyx.llm.utils.GEN_AI_MAX_TOKENS", 4096)
@pytest.mark.parametrize("enable_contextual_rag", [True, False])
def test_contextual_rag(
    embedder: DefaultIndexingEmbedder, enable_contextual_rag: bool
) -> None:
    short_section_1 = "This is a short section."
    long_section = (
        "This is a long section that should be split into multiple chunks. " * 100
    )
    short_section_2 = "This is another short section."
    short_section_3 = "This is another short section again."
    short_section_4 = "Final short section."
    semantic_identifier = "Test Document"

    document = Document(
        id="test_doc",
        source=DocumentSource.WEB,
        semantic_identifier=semantic_identifier,
        metadata={"tags": ["tag1", "tag2"]},
        doc_updated_at=None,
        sections=[
            TextSection(text=short_section_1, link="link1"),
            TextSection(text=short_section_2, link="link2"),
            TextSection(text=long_section, link="link3"),
            TextSection(text=short_section_3, link="link4"),
            TextSection(text=short_section_4, link="link5"),
        ],
    )
    indexing_documents = process_image_sections([document])

    mock_llm_invoke_count = 0

    def mock_llm_invoke(*args: Any, **kwargs: Any) -> ModelResponse:
        nonlocal mock_llm_invoke_count
        mock_llm_invoke_count += 1
        return ModelResponse(
            id=f"test-{mock_llm_invoke_count}",
            created="2024-01-01T00:00:00Z",
            choice=Choice(message=Message(content=f"Test{mock_llm_invoke_count}")),
        )

    llm_tokenizer = embedder.embedding_model.tokenizer

    mock_llm = Mock()
    mock_llm.config.max_input_tokens = get_max_input_tokens(
        model_provider=LlmProviderNames.OPENAI, model_name="gpt-4o"
    )
    mock_llm.invoke = mock_llm_invoke

    chunker = Chunker(
        tokenizer=embedder.embedding_model.tokenizer,
        enable_multipass=False,
        enable_contextual_rag=enable_contextual_rag,
    )
    chunks = chunker.chunk(indexing_documents)

    chunks = add_contextual_summaries(
        chunks=chunks,
        llm=mock_llm,
        tokenizer=llm_tokenizer,
        chunk_token_limit=chunker.chunk_token_limit * 2,
    )

    assert len(chunks) == 5
    assert short_section_1 in chunks[0].content
    assert short_section_3 in chunks[-1].content
    assert short_section_4 in chunks[-1].content
    assert "tag1" in chunks[0].metadata_suffix_keyword
    assert "tag2" in chunks[0].metadata_suffix_semantic

    doc_summary = "Test1" if enable_contextual_rag else ""
    chunk_context = ""
    count = 2
    for chunk in chunks:
        if enable_contextual_rag:
            chunk_context = f"Test{count}"
            count += 1
        assert chunk.doc_summary == doc_summary
        assert chunk.chunk_context == chunk_context
