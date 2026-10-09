"""External dependency tests for porting an index whose only change is its
vector quantization: the port copies stored vectors and makes no embedding
calls."""

import math
import random
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
from onyx.utils.pydantic_util import shallow_model_dump
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


class _CharTokenizer:
    """One token per character, so no real model loads."""

    def encode(self, text: str) -> list[int]:
        return [ord(ch) for ch in text]


class _RecordingEmbedder:
    """Returns a fixed vector and records the chunks it embeds."""

    def __init__(self, vector: list[float]) -> None:
        self.vector: list[float] = vector
        self.embedded: list[DocAwareChunk] = []

    def embed_chunks(self, chunks: list[DocAwareChunk]) -> list[IndexChunk]:
        self.embedded.extend(chunks)
        return [
            IndexChunk.model_construct(
                **shallow_model_dump(chunk),
                embeddings=ChunkEmbedding(
                    full_embedding=self.vector, mini_chunk_embeddings=[]
                ),
            )
            for chunk in chunks
        ]


def _vector(seed: int) -> list[float]:
    """A dense unit vector; one-hot vectors survive quantization exactly and
    would hide a lossy copy."""
    rng: random.Random = random.Random(seed)
    raw: list[float] = [rng.uniform(-1.0, 1.0) for _ in range(EMBEDDING_DIM)]
    norm: float = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


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


@pytest.mark.parametrize(
    "present_quantization,future_quantization",
    [
        (VectorQuantization.NONE, VectorQuantization.SCALAR_1_BIT),
        (VectorQuantization.SCALAR_1_BIT, VectorQuantization.NONE),
        (VectorQuantization.SCALAR_7_BIT, VectorQuantization.SCALAR_1_BIT),
    ],
)
def test_quantization_only_port_copies_vectors_without_embedding(
    tenant_context: None,  # noqa: ARG001
    present_quantization: VectorQuantization,
    future_quantization: VectorQuantization,
) -> None:
    """A quantization-only port writes every chunk with its original float32
    vector and unchanged fields, without calling the embedder."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    suffix: str = uuid.uuid4().hex[:8]
    present_name: str = f"test_copy_present_{suffix}"
    future_name: str = f"test_copy_future_{suffix}"
    present: OpenSearchDocumentIndex = _document_index(
        present_name, present_quantization
    )
    future: OpenSearchDocumentIndex = _document_index(future_name, future_quantization)
    present.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    future.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    with (
        OpenSearchIndexClient(index_name=present_name) as present_client,
        OpenSearchIndexClient(index_name=future_name) as future_client,
    ):
        original_vectors: dict[str, list[float]] = {
            f"{doc_id}:{chunk_id}": _vector(2 * i + chunk_id)
            for i, doc_id in enumerate(_DOC_IDS)
            for chunk_id in (0, 1)
        }
        try:
            present.index(
                chunks=[
                    make_chunk(
                        doc_id, chunk_id=chunk_id, content=f"{doc_id} {chunk_id}"
                    ).model_copy(
                        update={
                            "embeddings": ChunkEmbedding(
                                full_embedding=original_vectors[f"{doc_id}:{chunk_id}"],
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
                    original_vectors[key], abs=1e-6
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


def test_copy_vectors_reembeds_only_chunks_with_stripped_context(
    tenant_context: None,  # noqa: ARG001
) -> None:
    """With contextual RAG off in FUTURE, a page that mixes plain and
    context-bearing chunks copies the plain vector and re-embeds the others
    without their doc summary and chunk context."""
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")

    suffix: str = uuid.uuid4().hex[:8]
    present_name: str = f"test_copy_mixed_present_{suffix}"
    future_name: str = f"test_copy_mixed_future_{suffix}"
    present: OpenSearchDocumentIndex = _document_index(
        present_name, VectorQuantization.NONE
    )
    future: OpenSearchDocumentIndex = _document_index(
        future_name, VectorQuantization.SCALAR_1_BIT
    )
    present.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    future.verify_and_create_index_if_necessary(embedding_dim=EMBEDDING_DIM)
    doc_id: str = _DOC_IDS[0]
    context_by_chunk: dict[int, tuple[str, str]] = {
        0: ("", ""),
        1: ("Quarterly summary.", ""),
        2: ("", " Context for the third part."),
    }
    original_vectors: dict[int, list[float]] = {
        chunk_id: _vector(10 + chunk_id) for chunk_id in context_by_chunk
    }
    reembed_vector: list[float] = _vector(99)
    embedder: _RecordingEmbedder = _RecordingEmbedder(reembed_vector)
    with (
        OpenSearchIndexClient(index_name=present_name) as present_client,
        OpenSearchIndexClient(index_name=future_name) as future_client,
    ):
        try:
            present.index(
                chunks=[
                    make_chunk(
                        doc_id, chunk_id=chunk_id, content=f"part {chunk_id}"
                    ).model_copy(
                        update={
                            "doc_summary": doc_summary,
                            "chunk_context": chunk_context,
                            "embeddings": ChunkEmbedding(
                                full_embedding=original_vectors[chunk_id],
                                mini_chunk_embeddings=[],
                            ),
                        }
                    )
                    for chunk_id, (doc_summary, chunk_context) in (
                        context_by_chunk.items()
                    )
                ],
                indexing_metadata=make_indexing_metadata(
                    [doc_id], old_counts=[0], new_counts=[len(context_by_chunk)]
                ),
            )
            present_client.refresh_index()
            present_chunks: dict[str, DocumentChunk] = _stored_chunks(present_client)
            for chunk_id in (1, 2):
                stored: DocumentChunk = present_chunks[f"{doc_id}:{chunk_id}"]
                assert "".join(context_by_chunk[chunk_id]) in stored.content

            written, aborted = copy_present_chunks_to_future(
                present_client=present_client,
                future_index=future,
                doc_ids=[doc_id],
                strategy=ReembedStrategy.COPY_VECTORS,
                embedder=cast(IndexingEmbedder, embedder),
                present_tokenizer=cast(BaseTokenizer, _CharTokenizer()),
                tenant_state=TenantState(
                    tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                    multitenant=False,
                ),
                strip_stored_context=True,
            )
            future_client.refresh_index()

            assert (written, aborted) == (3, False)
            assert sorted(c.chunk_id for c in embedder.embedded) == [1, 2]
            future_chunks: dict[str, DocumentChunk] = _stored_chunks(future_client)
            plain: DocumentChunk = future_chunks[f"{doc_id}:0"]
            assert plain.content_vector == pytest.approx(original_vectors[0], abs=1e-6)
            for chunk_id in (1, 2):
                chunk: DocumentChunk = future_chunks[f"{doc_id}:{chunk_id}"]
                doc_summary, chunk_context = context_by_chunk[chunk_id]
                assert chunk.content_vector == pytest.approx(reembed_vector, abs=1e-6)
                assert chunk.doc_summary == ""
                assert chunk.chunk_context == ""
                assert (doc_summary or chunk_context) not in chunk.content
                assert f"part {chunk_id}" in chunk.content
        finally:
            present_client.delete_index()
            future_client.delete_index()
