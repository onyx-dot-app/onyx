from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from google.auth.credentials import Credentials

from onyx.cache.interface import CacheBackend
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import ConnectorStopSignal, Document, TextSection
from onyx.db.models import CloudEmbeddingProvider, SearchSettings
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
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
        provider_type=EmbeddingProvider.OPENAI,
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


def test_cached_passages_preserve_chunks_and_enrichment() -> None:
    store: dict[str, bytes] = {}
    cache = Mock(spec=CacheBackend)
    cache.get.side_effect = store.get
    cache.set.side_effect = lambda key, value, **_kwargs: store.__setitem__(key, value)
    model = Mock()
    model.encode.side_effect = lambda *, texts, **_kwargs: [
        [float(len(t)), 1.0] for t in texts
    ]
    callback = Mock(spec=IndexingHeartbeatInterface)
    callback.should_stop.return_value = False
    embedder = DefaultIndexingEmbedder(
        model_name="test",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
        search_settings_id=1,
        embedding_dimension=2,
        embedding_model=model,
        callback=callback,
    )
    chunks = [
        DocAwareChunk(
            chunk_id=i,
            blurb="text",
            content="text",
            source_links={0: f"link-{i}"},
            section_continuation=False,
            source_document=Document(
                id=f"doc-{i}",
                source=DocumentSource.FILE,
                semantic_identifier=f"doc-{i}",
                sections=[TextSection(text="text", link="")],
                metadata={},
            ),
            title_prefix="title",
            metadata_suffix_semantic="meta",
            metadata_suffix_keyword="",
            mini_chunk_texts=["mini", "text"],
            large_chunk_reference_ids=[],
            large_chunk_id=None,
            image_file_id=None,
            chunk_context="context",
            doc_summary="summary",
            contextual_rag_reserved_tokens=0,
        )
        for i in range(2)
    ]
    with (
        patch("onyx.indexing.embedder.PASSAGE_EMBEDDING_CACHE_ENABLED", True),
        patch(
            "onyx.natural_language_processing.passage_embedding_cache.get_cache_backend",
            return_value=cache,
        ),
    ):
        result = embedder.embed_chunks(chunks, tenant_id="tenant", request_id="request")
        model.encode.assert_called_once_with(
            texts=["titlesummarytextcontextmeta", "mini", "text"],
            text_type=EmbedTextType.PASSAGE,
            large_chunks_present=False,
            tenant_id="tenant",
            request_id="request",
        )
        assert [c.source_document.id for c in result] == ["doc-0", "doc-1"]
        assert [c.chunk_id for c in result] == [0, 1]
        assert [c.source_links for c in result] == [{0: "link-0"}, {0: "link-1"}]
        assert result[0].embeddings.mini_chunk_embeddings == [[4.0, 1.0], [4.0, 1.0]]
        model.encode.reset_mock()
        assert embedder.embed_chunks(chunks, tenant_id="tenant") == result
        model.encode.assert_not_called()
        chunks[0].metadata_suffix_semantic = "changed"
        embedder.embed_chunks(chunks, tenant_id="tenant")
        assert model.encode.call_args.kwargs["texts"] == [
            "titlesummarytextcontextchanged"
        ]
        # Large batches use a different truncation limit, even for matching text.
        large_chunk = chunks[0].model_copy(
            update={"mini_chunk_texts": None, "large_chunk_reference_ids": [0, 1]}
        )
        model.encode.reset_mock()
        embedder.embed_chunks([large_chunk], tenant_id="tenant")
        assert model.encode.call_args.kwargs["large_chunks_present"] is True
        assert model.encode.call_args.kwargs["texts"] == [
            "titlesummarytextcontextchanged"
        ]
        with patch("onyx.indexing.embedder.PASSAGE_EMBEDDING_CACHE_ENABLED", False):
            model.encode.reset_mock()
            embedder.embed_chunks([chunks[0], chunks[0]], tenant_id="tenant")
            assert len(model.encode.call_args.kwargs["texts"]) == 6
        model.encode.reset_mock()
        callback.should_stop.return_value = True
        with pytest.raises(ConnectorStopSignal):
            embedder.embed_chunks(chunks, tenant_id="tenant")
        model.encode.assert_not_called()


@pytest.mark.parametrize(
    "option,value",
    [
        ("search_settings_id", 2),
        ("embedding_dimension", 3),
        ("model_name", "other"),
        ("normalize", False),
        ("passage_prefix", "prefix"),
        ("provider_type", EmbeddingProvider.OPENAI),
        ("api_url", "https://example.com"),
        ("api_version", "v2"),
        ("deployment_name", "other"),
        ("reduced_dimension", 1),
    ],
)
def test_cache_scope_tracks_embedding_configuration(option: str, value: object) -> None:
    # The mapped fields and provider properties are read from a saved generation.
    if option == "search_settings_id":
        option = "id"
    elif option == "embedding_dimension":
        option = "model_dim"
    settings = Mock(spec=SearchSettings)
    for name in (
        "id",
        "model_name",
        "model_dim",
        "normalize",
        "query_prefix",
        "passage_prefix",
        "provider_type",
        "api_key",
        "api_url",
        "api_version",
        "deployment_name",
        "reduced_dimension",
    ):
        setattr(settings, name, None)
    settings.id, settings.model_name, settings.model_dim, settings.normalize = (
        1,
        "test",
        2,
        True,
    )
    with patch(
        "onyx.indexing.embedder.EmbeddingModel.from_db_model", return_value=Mock()
    ):
        original = DefaultIndexingEmbedder.from_db_search_settings(settings).cache_scope
        setattr(settings, option, value)
        assert (
            DefaultIndexingEmbedder.from_db_search_settings(settings).cache_scope
            != original
        )
