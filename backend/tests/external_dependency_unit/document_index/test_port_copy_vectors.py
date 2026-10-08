"""External dependency tests for porting an index whose only change is its
vector quantization: the port copies stored vectors and makes no embedding
calls."""

import uuid
from typing import cast

import pytest

from onyx.db.enums import VectorQuantization
from onyx.document_index.interfaces import TenantState
from onyx.document_index.opensearch.client import (
    OpenSearchIndexClient,
    wait_for_opensearch_with_timeout,
)
from onyx.document_index.opensearch.opensearch_document_index import (
    OpenSearchDocumentIndex,
)
from onyx.document_index.opensearch.port_copy import copy_present_chunks_to_future
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.indexing.embedder import IndexingEmbedder
from onyx.indexing.models import ChunkEmbedding, DocAwareChunk, IndexChunk
from onyx.indexing.port_reembed import ReembedStrategy
from onyx.natural_language_processing.utils import BaseTokenizer
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.document_index.conftest import (
    EMBEDDING_DIM,
    make_chunk,
    make_indexing_metadata,
)

_DOC_IDS: list[str] = ["copy_doc_a", "copy_doc_b"]


class _NoEmbedder:
    """Fails the test on any embedding call."""

    def embed_chunks(self, chunks: list[DocAwareChunk]) -> list[IndexChunk]:
        raise AssertionError(f"COPY_VECTORS embedded {len(chunks)} chunk(s)")


def _vector(position: int) -> list[float]:
    vector: list[float] = [0.0] * EMBEDDING_DIM
    vector[position] = 1.0
    return vector


def _document_index(
    name: str, quantization: VectorQuantization
) -> OpenSearchDocumentIndex:
    return OpenSearchDocumentIndex(
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
        index_name=name,
        embedding_dim=EMBEDDING_DIM,
        vector_quantization=quantization,
    )


def _stored_chunks(client: OpenSearchIndexClient) -> dict[str, DocumentChunk]:
    stored: dict[str, DocumentChunk] = {}
    for page in client.iter_chunks_with_vectors_for_doc_ids(
        _DOC_IDS,
        tenant_state=TenantState(
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, multitenant=False
        ),
    ):
        for chunk in page:
            stored[f"{chunk.document_id}:{chunk.chunk_index}"] = chunk
    return stored


def test_quantization_only_port_copies_vectors_without_embedding(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A float32 -> 1-bit port writes every chunk with its stored vector and
    unchanged fields, without calling the embedder."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    suffix: str = uuid.uuid4().hex[:8]
    present_name: str = f"test_copy_present_{suffix}"
    future_name: str = f"test_copy_future_{suffix}"
    present: OpenSearchDocumentIndex = _document_index(
        present_name, VectorQuantization.NONE
    )
    future: OpenSearchDocumentIndex = _document_index(
        future_name, VectorQuantization.SCALAR_1_BIT
    )
    present.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    future.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    with (
        OpenSearchIndexClient(index_name=present_name) as present_client,
        OpenSearchIndexClient(index_name=future_name) as future_client,
    ):
        try:
            present.index(
                chunks=[
                    make_chunk(
                        doc_id, chunk_id=chunk_id, content=f"{doc_id} {chunk_id}"
                    ).model_copy(
                        update={
                            "embeddings": ChunkEmbedding(
                                full_embedding=_vector(2 * i + chunk_id),
                                mini_chunk_embeddings=[],
                            )
                        }
                    )
                    for i, doc_id in enumerate(_DOC_IDS)
                    for chunk_id in (0, 1)
                ],
                indexing_metadata=make_indexing_metadata(
                    _DOC_IDS, old_counts=[0, 0], new_counts=[2, 2]
                ),
            )
            present_client.refresh_index()

            written, aborted = copy_present_chunks_to_future(
                present_client=present_client,
                future_index=future,
                doc_ids=_DOC_IDS,
                strategy=ReembedStrategy.COPY_VECTORS,
                embedder=cast(IndexingEmbedder, _NoEmbedder()),
                present_tokenizer=cast(BaseTokenizer, None),
                tenant_state=TenantState(
                    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                    multitenant=False,
                ),
                strip_stored_context=True,
            )
            future_client.refresh_index()

            assert (written, aborted) == (4, False)
            present_chunks: dict[str, DocumentChunk] = _stored_chunks(present_client)
            future_chunks: dict[str, DocumentChunk] = _stored_chunks(future_client)
            assert future_chunks.keys() == present_chunks.keys()
            for key, present_chunk in present_chunks.items():
                future_chunk: DocumentChunk = future_chunks[key]
                assert future_chunk.content_vector == pytest.approx(
                    present_chunk.content_vector
                )
                assert future_chunk.written_by_port
                assert (
                    future_chunk.model_copy(
                        update={"written_by_port": present_chunk.written_by_port}
                    )
                    == present_chunk
                )
        finally:
            present_client.delete_index()
            future_client.delete_index()
