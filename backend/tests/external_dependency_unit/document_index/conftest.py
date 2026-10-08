"""Shared fixtures for document_index external dependency tests.

Provides OpenSearch index setup, tenant context, and chunk helpers.
"""

import uuid
from collections.abc import Generator

import pytest

from onyx.access.models import DocumentAccess
from onyx.configs.constants import KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY, DocumentSource
from onyx.connectors.models import Document
from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import IndexingMetadata, TenantState
from onyx.document_index.opensearch.client import wait_for_opensearch_with_timeout
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.indexing.models import ChunkEmbedding, DocMetadataAwareIndexChunk
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.special_types import JSON_ro
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)

EMBEDDING_DIM = 128


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_chunk(
    doc_id: str,
    chunk_id: int = 0,
    content: str = "test content",
) -> DocMetadataAwareIndexChunk:
    """Create a chunk suitable for external dependency testing (128-dim embeddings)."""
    tenant_id = get_current_tenant_id()
    access = DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=True,
    )
    embeddings = ChunkEmbedding(
        full_embedding=[1.0] + [0.0] * (EMBEDDING_DIM - 1),
        mini_chunk_embeddings=[],
    )
    source_document = Document(
        id=doc_id,
        semantic_identifier="test_doc",
        source=DocumentSource.FILE,
        sections=[],
        metadata={},
        title="test title",
    )
    return DocMetadataAwareIndexChunk(
        tenant_id=tenant_id,
        access=access,
        document_sets=set(),
        user_project=[],
        personas=[],
        boost=0,
        aggregated_chunk_boost_factor=0,
        ancestor_hierarchy_node_ids=[],
        embeddings=embeddings,
        source_document=source_document,
        title_prefix="",
        metadata_suffix_keyword="",
        metadata_suffix_semantic="",
        contextual_rag_reserved_tokens=0,
        doc_summary="",
        chunk_context="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        chunk_id=chunk_id,
        blurb=content[:50],
        content=content,
        source_links={0: ""},
        image_file_id=None,
        section_continuation=False,
    )


def make_indexing_metadata(
    doc_ids: list[str],
    old_counts: list[int],
    new_counts: list[int],
) -> IndexingMetadata:
    return IndexingMetadata(
        doc_id_to_chunk_cnt_diff={
            doc_id: IndexingMetadata.ChunkCounts(
                old_chunk_cnt=old,
                new_chunk_cnt=new,
            )
            for doc_id, old, new in zip(doc_ids, old_counts, new_counts, strict=True)
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_context() -> Generator[None, None, None]:
    """Sets up tenant context for testing."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="module")
def test_index_name() -> Generator[str, None, None]:
    yield f"test_index_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def opensearch_index(
    tenant_context: None,  # noqa: ARG001
    test_index_name: str,
) -> Generator[OpenSearchDocumentIndex, None, None]:
    """Create an OpenSearch index and yield the underlying DocumentIndex."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    opensearch_idx = OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=test_index_name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=VectorQuantization.NONE,
    )
    opensearch_idx.verify_and_create_index_if_necessary(
        embedding_dim=EMBEDDING_DIM,
    )

    yield opensearch_idx


@pytest.fixture
def kv_progress_restored(
    tenant_context: None,  # noqa: ARG001
) -> Generator[None, None, None]:
    """Keeps the developer's stored backfill progress unchanged."""
    kv_store = get_kv_store()
    saved: JSON_ro | None
    try:
        saved = kv_store.load(KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY)
    except KvKeyNotFoundError:
        saved = None
    try:
        yield
    finally:
        if saved is None:
            try:
                kv_store.delete(KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY)
            except KvKeyNotFoundError:
                pass
        else:
            kv_store.store(KV_CC_PAIR_IDS_BACKFILL_PROGRESS_KEY, saved)
