"""Tests that persona IDs are correctly propagated through the indexing pipeline.

Covers Phase 1 (schema plumbing) and Phase 2 (write at index time) of the
unify-assistant-project-files plan.
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.access.models import DocumentAccess
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import TextSection
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk


def _make_index_chunk(
    doc_id: str = "test-file-id",
    content: str = "test content",
) -> IndexChunk:
    embedding = [0.1] * 10
    doc = Document(
        id=doc_id,
        semantic_identifier="test_file.txt",
        sections=[TextSection(text=content, link=None)],
        source=DocumentSource.USER_FILE,
        metadata={},
    )
    return IndexChunk(
        chunk_id=0,
        blurb=content[:50],
        content=content,
        source_links=None,
        image_file_id=None,
        section_continuation=False,
        source_document=doc,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        contextual_rag_reserved_tokens=0,
        doc_summary="",
        chunk_context="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        embeddings=ChunkEmbedding(
            full_embedding=embedding,
            mini_chunk_embeddings=[],
        ),
        title_embedding=None,
    )


def _make_access() -> DocumentAccess:
    return DocumentAccess.build(
        user_emails=["user@example.com"],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=False,
    )


def test_from_index_chunk_propagates_personas() -> None:
    """Personas list passed to from_index_chunk appears on the result."""
    chunk = _make_index_chunk()
    persona_ids = [10, 20, 30]

    aware_chunk = DocMetadataAwareIndexChunk.from_index_chunk(
        index_chunk=chunk,
        access=_make_access(),
        document_sets=set(),
        user_project=[1],
        personas=persona_ids,
        boost=0,
        aggregated_chunk_boost_factor=1.0,
        tenant_id="test_tenant",
    )

    assert aware_chunk.personas == persona_ids
    assert aware_chunk.user_project == [1]


def test_from_index_chunk_empty_personas() -> None:
    """An empty personas list is preserved (not turned into None or omitted)."""
    chunk = _make_index_chunk()

    aware_chunk = DocMetadataAwareIndexChunk.from_index_chunk(
        index_chunk=chunk,
        access=_make_access(),
        document_sets=set(),
        user_project=[],
        personas=[],
        boost=0,
        aggregated_chunk_boost_factor=1.0,
        tenant_id="test_tenant",
    )

    assert aware_chunk.personas == []


def _make_document(doc_id: str) -> Document:
    return Document(
        id=doc_id,
        semantic_identifier="test_file.txt",
        sections=[TextSection(text="test content", link=None)],
        source=DocumentSource.USER_FILE,
        metadata={},
    )


def _run_adapter_build(
    file_id: str,
    project_ids_map: dict[str, list[int]],
    persona_ids_map: dict[str, list[int]],
) -> list[DocMetadataAwareIndexChunk]:
    """Helper that runs UserFileIndexingAdapter.build_metadata_aware_chunks
    with all external dependencies mocked."""
    from onyx.indexing.adapters.user_file_indexing_adapter import (
        UserFileIndexingAdapter,
    )
    from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext

    chunk = _make_index_chunk(doc_id=file_id)
    doc = _make_document(doc_id=file_id)

    context = DocumentBatchPrepareContext(
        updatable_docs=[doc],
        id_to_boost_map={},
    )

    adapter = UserFileIndexingAdapter(tenant_id="test_tenant", db_session=MagicMock())

    with (
        patch(
            "onyx.indexing.adapters.user_file_indexing_adapter.fetch_user_project_ids_for_user_files",
            return_value=project_ids_map,
        ),
        patch(
            "onyx.indexing.adapters.user_file_indexing_adapter.fetch_persona_ids_for_user_files",
            return_value=persona_ids_map,
        ),
        patch(
            "onyx.indexing.adapters.user_file_indexing_adapter.get_access_for_user_files",
            return_value={file_id: _make_access()},
        ),
        patch(
            "onyx.indexing.adapters.user_file_indexing_adapter.fetch_chunk_counts_for_user_files",
            return_value=[(file_id, 0)],
        ),
        patch(
            "onyx.indexing.adapters.user_file_indexing_adapter.get_default_llm",
            side_effect=Exception("no LLM in tests"),
        ),
    ):
        result = adapter.build_metadata_aware_chunks(
            chunks_with_embeddings=[chunk],
            chunk_content_scores=[1.0],
            tenant_id="test_tenant",
            context=context,
        )

    return result.chunks


def test_build_metadata_aware_chunks_includes_persona_ids() -> None:
    """UserFileIndexingAdapter.build_metadata_aware_chunks writes persona IDs
    fetched from the DB into each chunk's metadata."""
    file_id = str(uuid4())
    persona_ids = [5, 12]
    project_ids = [3]

    chunks = _run_adapter_build(
        file_id=file_id,
        project_ids_map={file_id: project_ids},
        persona_ids_map={file_id: persona_ids},
    )

    assert len(chunks) == 1
    assert chunks[0].personas == persona_ids
    assert chunks[0].user_project == project_ids


def test_build_metadata_aware_chunks_missing_file_defaults_to_empty() -> None:
    """When a file has no persona or project associations in the DB, the
    adapter should default to empty lists (not KeyError or None)."""
    file_id = str(uuid4())

    chunks = _run_adapter_build(
        file_id=file_id,
        project_ids_map={},
        persona_ids_map={},
    )

    assert len(chunks) == 1
    assert chunks[0].personas == []
    assert chunks[0].user_project == []
