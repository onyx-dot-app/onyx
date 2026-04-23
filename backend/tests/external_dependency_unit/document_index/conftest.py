"""Shared fixtures for document_index external dependency tests.

Provides Vespa and OpenSearch index setup, tenant context, and chunk helpers.
"""

import os
import time
import uuid
from collections.abc import Generator
from unittest.mock import patch

import httpx
import pytest

from onyx.access.models import DocumentAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import Document
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.opensearch.client import wait_for_opensearch_with_timeout
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchOldDocumentIndex,
)
from onyx.document_index.vespa.index import VespaIndex
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa.shared_utils.utils import wait_for_vespa_with_timeout
from onyx.indexing.models import ChunkEmbedding
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.constants import TEST_TENANT_ID

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
        title_embedding=[1.0] + [0.0] * (EMBEDDING_DIM - 1),
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
            for doc_id, old, new in zip(doc_ids, old_counts, new_counts)
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tenant_context() -> Generator[None, None, None]:
    """Sets up tenant context for testing."""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@pytest.fixture(scope="module")
def test_index_name() -> Generator[str, None, None]:
    yield f"test_index_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def httpx_client() -> Generator[httpx.Client, None, None]:
    client = get_vespa_http_client()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="module")
def vespa_index(
    httpx_client: httpx.Client,
    tenant_context: None,  # noqa: ARG001
    test_index_name: str,
) -> Generator[VespaIndex, None, None]:
    """Create a Vespa index, wait for schema readiness, and yield it."""
    vespa_idx = VespaIndex(
        index_name=test_index_name,
        secondary_index_name=None,
        large_chunks_enabled=False,
        secondary_large_chunks_enabled=None,
        multitenant=MULTI_TENANT,
        httpx_client=httpx_client,
    )
    backend_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    with patch("os.getcwd", return_value=backend_dir):
        vespa_idx.ensure_indices_exist(
            primary_embedding_dim=EMBEDDING_DIM,
            primary_embedding_precision=EmbeddingPrecision.FLOAT,
            secondary_index_embedding_dim=None,
            secondary_index_embedding_precision=None,
        )
    if not wait_for_vespa_with_timeout(wait_limit=90):
        pytest.fail("Vespa is not available.")

    # Wait until the schema is actually ready for writes on content nodes. We
    # probe by attempting a PUT; 200 means the schema is live, 400 means not
    # yet. This is only temporary until we entirely move off of Vespa.
    probe_doc = {
        "fields": {
            "document_id": "__probe__",
            "chunk_id": 0,
            "blurb": "",
            "title": "",
            "skip_title": True,
            "content": "",
            "content_summary": "",
            "source_type": "file",
            "source_links": "null",
            "semantic_identifier": "",
            "section_continuation": False,
            "large_chunk_reference_ids": [],
            "metadata": "{}",
            "metadata_list": [],
            "metadata_suffix": "",
            "chunk_context": "",
            "doc_summary": "",
            "embeddings": {"full_chunk": [1.0] + [0.0] * (EMBEDDING_DIM - 1)},
            "access_control_list": {},
            "document_sets": {},
            "image_file_name": None,
            "user_project": [],
            "personas": [],
            "boost": 0.0,
            "aggregated_chunk_boost_factor": 0.0,
            "primary_owners": [],
            "secondary_owners": [],
        }
    }
    probe_url = (
        f"http://localhost:8081/document/v1/default/{test_index_name}/docid/__probe__"
    )
    schema_ready = False
    for _ in range(60):
        resp = httpx_client.post(probe_url, json=probe_doc)
        if resp.status_code == 200:
            schema_ready = True
            httpx_client.delete(probe_url)
            break
        time.sleep(1)
    if not schema_ready:
        pytest.fail(f"Vespa schema '{test_index_name}' did not become ready in time.")

    yield vespa_idx


@pytest.fixture(scope="module")
def opensearch_old_index(
    tenant_context: None,  # noqa: ARG001
    test_index_name: str,
) -> Generator[OpenSearchOldDocumentIndex, None, None]:
    """Create an OpenSearch index via the old adapter and yield it."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    opensearch_idx = OpenSearchOldDocumentIndex(
        index_name=test_index_name,
        embedding_dim=EMBEDDING_DIM,
        embedding_precision=EmbeddingPrecision.FLOAT,
        secondary_index_name=None,
        secondary_embedding_dim=None,
        secondary_embedding_precision=None,
        large_chunks_enabled=False,
        secondary_large_chunks_enabled=None,
        multitenant=MULTI_TENANT,
    )
    opensearch_idx.ensure_indices_exist(
        primary_embedding_dim=EMBEDDING_DIM,
        primary_embedding_precision=EmbeddingPrecision.FLOAT,
        secondary_index_embedding_dim=None,
        secondary_index_embedding_precision=None,
    )

    yield opensearch_idx
