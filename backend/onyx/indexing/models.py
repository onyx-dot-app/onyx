import contextlib
from collections.abc import Generator
from typing import Optional
from typing import Protocol
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic import Field

from onyx.access.models import DocumentAccess
from onyx.connectors.models import Document
from onyx.db.enums import EmbeddingPrecision
from onyx.utils.logger import setup_logger
from shared_configs.enums import EmbeddingProvider
from shared_configs.model_server_models import Embedding

if TYPE_CHECKING:
    from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from sqlalchemy.engine.util import TransactionalContext

if TYPE_CHECKING:
    from onyx.db.models import SearchSettings


logger = setup_logger()


class ChunkEmbedding(BaseModel):
    full_embedding: Embedding
    mini_chunk_embeddings: list[Embedding]


class BaseChunk(BaseModel):
    chunk_id: int
    # The first sentence(s) of the first Section of the chunk
    blurb: str
    content: str
    # Holds the link and the offsets into the raw Chunk text
    source_links: dict[int, str] | None
    image_file_id: str | None
    # True if this Chunk's start is not at the start of a Section
    section_continuation: bool


class DocAwareChunk(BaseChunk):
    # During indexing flow, we have access to a complete "Document"
    # During inference we only have access to the document id and do not reconstruct the Document
    source_document: Document

    # This could be an empty string if the title is too long and taking up too much of the chunk
    # This does not mean necessarily that the document does not have a title
    title_prefix: str

    # During indexing we also (optionally) build a metadata string from the metadata dict
    # This is also indexed so that we can strip it out after indexing, this way it supports
    # multiple iterations of metadata representation for backwards compatibility
    metadata_suffix_semantic: str
    metadata_suffix_keyword: str

    # This is the number of tokens reserved for contextual RAG
    # in the chunk. doc_summary and chunk_context conbined should
    # contain at most this many tokens.
    contextual_rag_reserved_tokens: int
    # This is the summary for the document generated for contextual RAG
    doc_summary: str
    # This is the context for this chunk generated for contextual RAG
    chunk_context: str

    mini_chunk_texts: list[str] | None

    large_chunk_id: int | None

    large_chunk_reference_ids: list[int] = Field(default_factory=list)

    def to_short_descriptor(self) -> str:
        """Used when logging the identity of a chunk"""
        return f"{self.source_document.to_short_descriptor()} Chunk ID: {self.chunk_id}"

    def get_link(self) -> str | None:
        return (
            self.source_document.sections[0].link
            if self.source_document.sections
            else None
        )


class IndexChunk(DocAwareChunk):
    embeddings: ChunkEmbedding
    title_embedding: Embedding | None


# TODO(rkuo): currently, this extra metadata sent during indexing is just for speed,
# but full consistency happens on background sync
class DocMetadataAwareIndexChunk(IndexChunk):
    """An `IndexChunk` that contains all necessary metadata to be indexed. This includes
    the following:

    access: holds all information about which users should have access to the
            source document for this chunk.
    document_sets: all document sets the source document for this chunk is a part
                   of. This is used for filtering / personas.
    boost: influences the ranking of this chunk at query time. Positive -> ranked higher,
           negative -> ranked lower. Not included in aggregated boost calculation
           for legacy reasons.
    aggregated_chunk_boost_factor: represents the aggregated chunk-level boost (currently: information content)
    """

    tenant_id: str
    access: "DocumentAccess"
    document_sets: set[str]
    user_project: list[int]
    boost: int
    aggregated_chunk_boost_factor: float

    @classmethod
    def from_index_chunk(
        cls,
        index_chunk: IndexChunk,
        access: "DocumentAccess",
        document_sets: set[str],
        user_project: list[int],
        boost: int,
        aggregated_chunk_boost_factor: float,
        tenant_id: str,
    ) -> "DocMetadataAwareIndexChunk":
        index_chunk_data = index_chunk.model_dump()
        return cls(
            **index_chunk_data,
            access=access,
            document_sets=document_sets,
            user_project=user_project,
            boost=boost,
            aggregated_chunk_boost_factor=aggregated_chunk_boost_factor,
            tenant_id=tenant_id,
        )


class EmbeddingModelDetail(BaseModel):
    id: int | None = None
    model_name: str
    normalize: bool
    query_prefix: str | None
    passage_prefix: str | None
    api_url: str | None = None
    provider_type: EmbeddingProvider | None = None
    api_key: str | None = None

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}

    @classmethod
    def from_db_model(
        cls,
        search_settings: "SearchSettings",
    ) -> "EmbeddingModelDetail":
        return cls(
            id=search_settings.id,
            model_name=search_settings.model_name,
            normalize=search_settings.normalize,
            query_prefix=search_settings.query_prefix,
            passage_prefix=search_settings.passage_prefix,
            provider_type=search_settings.provider_type,
            api_key=search_settings.api_key,
            api_url=search_settings.api_url,
        )


# Additional info needed for indexing time
class IndexingSetting(EmbeddingModelDetail):
    model_dim: int
    index_name: str | None
    multipass_indexing: bool
    embedding_precision: EmbeddingPrecision
    reduced_dimension: int | None = None

    background_reindex_enabled: bool = True
    enable_contextual_rag: bool
    contextual_rag_llm_name: str | None = None
    contextual_rag_llm_provider: str | None = None

    # This disables the "model_" protected namespace for pydantic
    model_config = {"protected_namespaces": ()}

    @property
    def final_embedding_dim(self) -> int:
        if self.reduced_dimension:
            return self.reduced_dimension
        return self.model_dim

    @classmethod
    def from_db_model(cls, search_settings: "SearchSettings") -> "IndexingSetting":
        return cls(
            model_name=search_settings.model_name,
            model_dim=search_settings.model_dim,
            normalize=search_settings.normalize,
            query_prefix=search_settings.query_prefix,
            passage_prefix=search_settings.passage_prefix,
            provider_type=search_settings.provider_type,
            index_name=search_settings.index_name,
            multipass_indexing=search_settings.multipass_indexing,
            embedding_precision=search_settings.embedding_precision,
            reduced_dimension=search_settings.reduced_dimension,
            background_reindex_enabled=search_settings.background_reindex_enabled,
            enable_contextual_rag=search_settings.enable_contextual_rag,
        )


class MultipassConfig(BaseModel):
    multipass_indexing: bool
    enable_large_chunks: bool


class UpdatableChunkData(BaseModel):
    chunk_id: int
    document_id: str
    boost_score: float


class BuildMetadataAwareChunksResult(BaseModel):
    chunks: list[DocMetadataAwareIndexChunk]
    doc_id_to_previous_chunk_cnt: dict[str, int]
    doc_id_to_new_chunk_cnt: dict[str, int]
    user_file_id_to_raw_text: dict[str, str]
    user_file_id_to_token_count: dict[str, int | None]


class IndexingBatchAdapter(Protocol):
    def prepare(
        self, documents: list[Document], ignore_time_skip: bool
    ) -> Optional["DocumentBatchPrepareContext"]: ...

    @contextlib.contextmanager
    def lock_context(
        self, documents: list[Document]
    ) -> Generator[TransactionalContext, None, None]:
        """Provide a transaction/row-lock context for critical updates."""

    def build_metadata_aware_chunks(
        self,
        chunks_with_embeddings: list[IndexChunk],
        chunk_content_scores: list[float],
        tenant_id: str,
        context: "DocumentBatchPrepareContext",
    ) -> BuildMetadataAwareChunksResult: ...

    def post_index(
        self,
        context: "DocumentBatchPrepareContext",
        updatable_chunk_data: list[UpdatableChunkData],
        filtered_documents: list[Document],
        result: BuildMetadataAwareChunksResult,
    ) -> None: ...
