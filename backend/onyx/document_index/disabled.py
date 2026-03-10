"""A DocumentIndex implementation that raises on every operation.

Used as a safety net when DISABLE_VECTOR_DB is True. Any code path that
accidentally reaches the vector DB layer will fail loudly instead of timing
out against a nonexistent Vespa/OpenSearch instance.
"""

from typing import Any

from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import DocumentInsertionRecord
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.model_server_models import Embedding

VECTOR_DB_DISABLED_ERROR = (
    "Vector DB is disabled (DISABLE_VECTOR_DB=true). "
    "This operation requires a vector database."
)


class DisabledDocumentIndex(DocumentIndex):
    """A DocumentIndex where every method raises RuntimeError.

    Returned by the factory when DISABLE_VECTOR_DB is True so that any
    accidental vector-DB call surfaces immediately.
    """

    def __init__(
        self,
        index_name: str = "disabled",
        secondary_index_name: str | None = None,
        *args: Any,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        self.index_name = index_name
        self.secondary_index_name = secondary_index_name

    # ------------------------------------------------------------------
    # Verifiable
    # ------------------------------------------------------------------
    def ensure_indices_exist(
        self,
        primary_embedding_dim: int,  # noqa: ARG002
        primary_embedding_precision: EmbeddingPrecision,  # noqa: ARG002
        secondary_index_embedding_dim: int | None,  # noqa: ARG002
        secondary_index_embedding_precision: EmbeddingPrecision | None,  # noqa: ARG002
    ) -> None:
        # No-op: there are no indices to create when the vector DB is disabled.
        pass

    @staticmethod
    def register_multitenant_indices(
        indices: list[str],  # noqa: ARG002, ARG004
        embedding_dims: list[int],  # noqa: ARG002, ARG004
        embedding_precisions: list[EmbeddingPrecision],  # noqa: ARG002, ARG004
    ) -> None:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    # ------------------------------------------------------------------
    # Indexable
    # ------------------------------------------------------------------
    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],  # noqa: ARG002
        index_batch_params: IndexBatchParams,  # noqa: ARG002
    ) -> set[DocumentInsertionRecord]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    # ------------------------------------------------------------------
    # Deletable
    # ------------------------------------------------------------------
    def delete_single(
        self,
        doc_id: str,  # noqa: ARG002
        *,
        tenant_id: str,  # noqa: ARG002
        chunk_count: int | None,  # noqa: ARG002
    ) -> int:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    # ------------------------------------------------------------------
    # Updatable
    # ------------------------------------------------------------------
    def update_single(
        self,
        doc_id: str,  # noqa: ARG002
        *,
        tenant_id: str,  # noqa: ARG002
        chunk_count: int | None,  # noqa: ARG002
        fields: VespaDocumentFields | None,  # noqa: ARG002
        user_fields: VespaDocumentUserFields | None,  # noqa: ARG002
    ) -> None:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    # ------------------------------------------------------------------
    # IdRetrievalCapable
    # ------------------------------------------------------------------
    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],  # noqa: ARG002
        filters: IndexFilters,  # noqa: ARG002
        batch_retrieval: bool = False,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    # ------------------------------------------------------------------
    # HybridCapable
    # ------------------------------------------------------------------
    def hybrid_retrieval(
        self,
        query: str,  # noqa: ARG002
        query_embedding: Embedding,  # noqa: ARG002
        final_keywords: list[str] | None,  # noqa: ARG002
        filters: IndexFilters,  # noqa: ARG002
        hybrid_alpha: float,  # noqa: ARG002
        time_decay_multiplier: float,  # noqa: ARG002
        num_to_retrieve: int,  # noqa: ARG002
        ranking_profile_type: QueryExpansionType,  # noqa: ARG002
        title_content_ratio: float | None = None,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    # ------------------------------------------------------------------
    # AdminCapable
    # ------------------------------------------------------------------
    def admin_retrieval(
        self,
        query: str,  # noqa: ARG002
        query_embedding: Embedding,  # noqa: ARG002
        filters: IndexFilters,  # noqa: ARG002
        num_to_retrieve: int = 10,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)

    # ------------------------------------------------------------------
    # RandomCapable
    # ------------------------------------------------------------------
    def random_retrieval(
        self,
        filters: IndexFilters,  # noqa: ARG002
        num_to_retrieve: int = 10,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        raise RuntimeError(VECTOR_DB_DISABLED_ERROR)
