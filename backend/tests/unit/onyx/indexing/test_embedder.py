from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from google.auth.credentials import Credentials

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document, TextSection
from onyx.db.models import CloudEmbeddingProvider, SearchSettings
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.models import ChunkEmbedding, DocAwareChunk, IndexChunk
from shared_configs.enums import EmbeddingProvider, EmbedTextType


def test_saved_workload_identity_embeds_indexing_chunks_and_titles() -> None:
    settings = SearchSettings(
        model_name="gemini-embedding-2",
        normalize=False,
        query_prefix=None,
        passage_prefix=None,
        provider_type=EmbeddingProvider.GOOGLE,
        reduced_dimension=2,
        cloud_provider=CloudEmbeddingProvider(
            provider_type=EmbeddingProvider.GOOGLE,
            api_key=None,
            vertex_config={
                "auth_method": "workload_identity",
                "project_id": "vertex-project",
                "location": "global",
            },
        ),
    )
    document = Document(
        id="test_doc",
        source=DocumentSource.FILE,
        semantic_identifier="Launch project",
        title="Launch project",
        sections=[TextSection(text="The project is Emerald Heron.", link="")],
        metadata={},
    )
    chunk = DocAwareChunk(
        chunk_id=0,
        blurb="The project is Emerald Heron.",
        content="The project is Emerald Heron.",
        source_links={0: ""},
        section_continuation=False,
        source_document=document,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        mini_chunk_texts=None,
        large_chunk_reference_ids=[],
        large_chunk_id=None,
        image_file_id=None,
        chunk_context="",
        doc_summary="",
        contextual_rag_reserved_tokens=0,
    )
    response = MagicMock()
    response.embeddings = [MagicMock(values=[0.1, 0.2])]
    client = MagicMock()
    client.aio.models.embed_content = AsyncMock(return_value=response)
    client.aio.aclose = AsyncMock()
    with (
        patch(
            "google.auth.default",
            return_value=(MagicMock(spec=Credentials), "cluster-project"),
        ),
        patch("google.genai.Client", return_value=client) as genai,
        patch("onyx.natural_language_processing.search_nlp_models.get_tokenizer"),
    ):
        embedder = DefaultIndexingEmbedder.from_db_search_settings(settings)
        result = embedder.embed_chunks([chunk])

    assert result[0].embeddings.full_embedding == [0.1, 0.2]
    # Only the chunk text is embedded; titles get no separate embedding.
    assert client.aio.models.embed_content.call_count == 1
    assert genai.call_args.kwargs["project"] == "vertex-project"
    assert genai.call_args.kwargs["location"] == "global"


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
        provider_type=EmbeddingProvider.OPENAI_COMPATIBLE,
    )

    # Mock the encode method of the embedding model
    mock_embedding_model.return_value.encode.side_effect = [
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],  # Main chunk embeddings
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
    # Verify the embedding model was called exactly as follows
    mock_embedding_model.return_value.encode.assert_any_call(
        texts=[f"Title: {doc_summary}Test chunk{chunk_context}"],
        text_type=EmbedTextType.PASSAGE,
        large_chunks_present=False,
        tenant_id=None,
        request_id=None,
    )
    # Titles get no separate embedding call.
    assert mock_embedding_model.return_value.encode.call_count == 1
