"""A DocumentIndex implementation that raises on every operation.

Used as a safety net when DISABLE_VECTOR_DB is True. Any code path that
accidentally reaches the vector DB layer will fail loudly instead of timing
out against a nonexistent Vespa/OpenSearch instance.
"""

from collections.abc import Iterable

from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import DocumentInsertionRecord
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.model_server_models import Embedding

VECTOR_DB_DISABLED_ERROR = "Vector DB is disabled (DISABLE_VECTOR_DB=true). This operation requires a vector database."


class DisabledDocumentIndex(DocumentIndex):
    """A DocumentIndex where every method raises RuntimeError.

    Returned by the factory when DISABLE_VECTOR_DB is True so any accidental
    vector-DB call surfaces immediately. `verify_and_create_index_if_necessary`
    is a no-op so setup paths can still iterate over the configured indices.
    """

    def verify_and_create_index_if_necessary(
        self,
        embedding_dim: int,  # noqa: ARG002
        embedding_precision: EmbeddingPrecision,  # noqa: ARG002
    ) -> None:
        # No-op: there are no indices to create when the vector DB is disabled.
        return None

    def index(
        self,
        chunks: Iterable[DocMetadataAwareIndexChunk],  # noqa: ARG002
        indexing_metadata: IndexingMetadata,  # noqa: ARG002
    ) -> list[DocumentInsertionRecord]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    def delete(
        self,
        document_id: str,  # noqa: ARG002
        chunk_count: int | None = None,  # noqa: ARG002
    ) -> int:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    def update(
        self,
        update_requests: list[MetadataUpdateRequest],  # noqa: ARG002
    ) -> None:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],  # noqa: ARG002
        filters: IndexFilters,  # noqa: ARG002
        batch_retrieval: bool = False,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    def hybrid_retrieval(
        self,
        query: str,  # noqa: ARG002
        query_embedding: Embedding,  # noqa: ARG002
        final_keywords: list[str] | None,  # noqa: ARG002
        query_type: QueryType,  # noqa: ARG002
        filters: IndexFilters,  # noqa: ARG002
        num_to_retrieve: int,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    def keyword_retrieval(
        self,
        query: str,  # noqa: ARG002
        filters: IndexFilters,  # noqa: ARG002
        num_to_retrieve: int,  # noqa: ARG002
        include_hidden: bool = False,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    def semantic_retrieval(
        self,
        query_embedding: Embedding,  # noqa: ARG002
        filters: IndexFilters,  # noqa: ARG002
        num_to_retrieve: int,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    def random_retrieval(
        self,
        filters: IndexFilters,  # noqa: ARG002
        num_to_retrieve: int = 10,  # noqa: ARG002
        dirty: bool | None = None,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)
