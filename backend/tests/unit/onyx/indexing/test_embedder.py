from collections.abc import Generator
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import IndexChunk
from shared_configs.enums import EmbeddingProvider
from shared_configs.enums import EmbedTextType


@pytest.fixture
def mock_embedding_model() -> Generator[Mock, None, None]:
    with patch("onyx.indexing.embedder.EmbeddingModel") as mock:
        yield mock


@pytest.mark.parametrize(
    "chunk_context, doc_summary",
    [("Test chunk context", "Test document summary"), ("", "")],
)
def test_default_indexing_embedder_embed_chunks(
    mock_embedding_model: Mock, chunk_context: str, doc_summary: str
) -> None:
    # Setup
    embedder = DefaultIndexingEmbedder(
        model_name="test-model",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
        provider_type=EmbeddingProvider.OPENAI,
    )

    # Mock the encode method of the embedding model
    mock_embedding_model.return_value.encode.side_effect = [
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],  # Main chunk embeddings
        [[7.0, 8.0, 9.0]],  # Title embedding
    ]

    # Create test input
    source_doc = Document(
        id="test_doc",
        source=DocumentSource.WEB,
        semantic_identifier="Test Document",
        metadata={"tags": ["tag1", "tag2"]},
        doc_updated_at=None,
        sections=[
            TextSection(text="This is a short section.", link="link1"),
        ],
    )
    chunks: list[DocAwareChunk] = [
        DocAwareChunk(
            chunk_id=1,
            blurb="This is a short section.",
            content="Test chunk",
            source_links={0: "link1"},
            section_continuation=False,
            source_document=source_doc,
            title_prefix="Title: ",
            metadata_suffix_semantic="",
            metadata_suffix_keyword="",
            mini_chunk_texts=None,
            large_chunk_reference_ids=[],
            large_chunk_id=None,
            image_file_id=None,
            chunk_context=chunk_context,
            doc_summary=doc_summary,
            contextual_rag_reserved_tokens=200,
        )
    ]

    # Execute
    result: list[IndexChunk] = embedder.embed_chunks(chunks)

    # Assert
    assert len(result) == 1
    assert isinstance(result[0], IndexChunk)
    assert result[0].content == "Test chunk"
    assert result[0].embeddings == ChunkEmbedding(
        full_embedding=[1.0, 2.0, 3.0],
        mini_chunk_embeddings=[],
    )
    assert result[0].title_embedding == [7.0, 8.0, 9.0]

    # Verify the embedding model was called exactly as follows
    mock_embedding_model.return_value.encode.assert_any_call(
        texts=[f"Title: {doc_summary}Test chunk{chunk_context}"],
        text_type=EmbedTextType.PASSAGE,
        large_chunks_present=False,
        tenant_id=None,
        request_id=None,
    )
    # Same for title only embedding call
    mock_embedding_model.return_value.encode.assert_any_call(
        ["Test Document"],
        text_type=EmbedTextType.PASSAGE,
        tenant_id=None,
        request_id=None,
    )
