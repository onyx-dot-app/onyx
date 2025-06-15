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
from onyx.indexing.indexing_pipeline import _get_aggregated_chunk_boost_factor
from onyx.indexing.indexing_pipeline import add_contextual_summaries
from onyx.indexing.indexing_pipeline import filter_documents
from onyx.indexing.indexing_pipeline import process_image_sections
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import IndexChunk
from onyx.llm.utils import get_max_input_tokens
from onyx.natural_language_processing.search_nlp_models import (
    ContentClassificationPrediction,
)
from shared_configs.configs import (
    INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH,
)


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


# Tests for get_aggregated_boost_factor


def create_test_chunk(
    content: str, chunk_id: int = 0, doc_id: str = "test_doc"
) -> IndexChunk:
    doc = Document(
        id=doc_id,
        semantic_identifier="test doc",
        sections=[],
        source=DocumentSource.FILE,
        metadata={},
    )
    return IndexChunk(
        chunk_id=chunk_id,
        content=content,
        source_document=doc,
        blurb=content[:50],  # First 50 chars as blurb
        source_links={0: "test_link"},
        section_continuation=False,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        large_chunk_reference_ids=[],
        embeddings=ChunkEmbedding(full_embedding=[], mini_chunk_embeddings=[]),
        title_embedding=None,
        image_file_id=None,
        chunk_context="",
        doc_summary="",
        contextual_rag_reserved_tokens=200,
    )


def test_get_aggregated_boost_factor() -> None:
    # Create test chunks - mix of short and long content
    chunks = [
        create_test_chunk("Short content", 0),
        create_test_chunk(
            "Long " * (INDEXING_INFORMATION_CONTENT_CLASSIFICATION_CUTOFF_LENGTH + 1), 1
        ),
        create_test_chunk("Another short chunk", 2),
    ]

    # Mock the classification model
    mock_model = Mock()
    mock_model.predict.return_value = [
        ContentClassificationPrediction(predicted_label=1, content_boost_factor=0.8),
        ContentClassificationPrediction(predicted_label=1, content_boost_factor=0.9),
    ]

    # Execute the function
    boost_scores = _get_aggregated_chunk_boost_factor(
        chunks=chunks, information_content_classification_model=mock_model
    )

    # Assertions
    assert len(boost_scores) == 3

    # Check that long content got default boost
    assert boost_scores[1] == 1.0

    # Check that short content got predicted boosts
    assert boost_scores[0] == 0.8
    assert boost_scores[2] == 0.9

    # Verify model was only called once with the short chunks
    mock_model.predict.assert_called_once()
    assert len(mock_model.predict.call_args[0][0]) == 2


def test_get_aggregated_boost_factorilure() -> None:
    chunks = [
        create_test_chunk("Short content 1", 0),
        create_test_chunk("Short content 2", 1),
    ]

    # Mock model to fail on batch prediction but succeed on individual predictions
    mock_model = Mock()
    mock_model.predict.side_effect = [
        Exception("Batch prediction failed"),  # First call fails
        [
            ContentClassificationPrediction(predicted_label=1, content_boost_factor=0.7)
        ],  # Individual calls succeed
        [ContentClassificationPrediction(predicted_label=1, content_boost_factor=0.8)],
    ]

    # Execute
    boost_scores = _get_aggregated_chunk_boost_factor(
        chunks=chunks, information_content_classification_model=mock_model
    )

    # Assertions
    assert len(boost_scores) == 2
    assert boost_scores == [0.7, 0.8]


def test_get_aggregated_boost_factor_individual_failure() -> None:
    chunks = [
        create_test_chunk("Short content", 0),
        create_test_chunk("Short content", 1),
    ]

    # Mock model to fail on both batch and individual prediction
    mock_model = Mock()
    mock_model.predict.side_effect = Exception("Prediction failed")

    # Execute and verify it raises an exception
    with pytest.raises(Exception) as exc_info:
        _get_aggregated_chunk_boost_factor(
            chunks=chunks, information_content_classification_model=mock_model
        )

    assert "Failed to predict content classification for chunk" in str(exc_info.value)


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

    def mock_llm_invoke(self: Any, *args: Any, **kwargs: Any) -> Mock:
        nonlocal mock_llm_invoke_count
        mock_llm_invoke_count += 1
        m = Mock()
        m.content = f"Test{mock_llm_invoke_count}"
        return m

    llm_tokenizer = embedder.embedding_model.tokenizer

    mock_llm = Mock()
    mock_llm.config.max_input_tokens = get_max_input_tokens(
        model_provider="openai", model_name="gtp-4o"
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
