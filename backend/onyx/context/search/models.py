from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.constants import DocumentSource
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.enums import SearchType
from onyx.db.models import Persona
from onyx.db.models import SearchSettings
from onyx.indexing.models import BaseChunk
from onyx.indexing.models import IndexingSetting
from shared_configs.enums import RerankerProvider
from shared_configs.model_server_models import Embedding


MAX_METRICS_CONTENT = (
    200  # Just need enough characters to identify where in the doc the chunk is
)


class QueryExpansions(BaseModel):
    keywords_expansions: list[str] | None = None
    semantic_expansions: list[str] | None = None


class RerankingDetails(BaseModel):
    # If model is None (or num_rerank is 0), then reranking is turned off
    rerank_model_name: str | None
    rerank_api_url: str | None
    rerank_provider_type: RerankerProvider | None
    rerank_api_key: str | None = None

    num_rerank: int

    # For faster flows where the results should start immediately
    # this more time intensive step can be skipped
    disable_rerank_for_streaming: bool = False

    @classmethod
    def from_db_model(cls, search_settings: SearchSettings) -> "RerankingDetails":
        return cls(
            rerank_model_name=search_settings.rerank_model_name,
            rerank_provider_type=search_settings.rerank_provider_type,
            rerank_api_key=search_settings.rerank_api_key,
            num_rerank=search_settings.num_rerank,
            rerank_api_url=search_settings.rerank_api_url,
        )


class InferenceSettings(RerankingDetails):
    # Empty for no additional expansion
    multilingual_expansion: list[str]


class SearchSettingsCreationRequest(InferenceSettings, IndexingSetting):
    @classmethod
    def from_db_model(
        cls, search_settings: SearchSettings
    ) -> "SearchSettingsCreationRequest":
        inference_settings = InferenceSettings.from_db_model(search_settings)
        indexing_setting = IndexingSetting.from_db_model(search_settings)

        return cls(**inference_settings.model_dump(), **indexing_setting.model_dump())


class SavedSearchSettings(InferenceSettings, IndexingSetting):
    @classmethod
    def from_db_model(cls, search_settings: SearchSettings) -> "SavedSearchSettings":
        return cls(
            # Indexing Setting
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
            # Whether switching to this model requires re-indexing
            background_reindex_enabled=search_settings.background_reindex_enabled,
            enable_contextual_rag=search_settings.enable_contextual_rag,
            contextual_rag_llm_name=search_settings.contextual_rag_llm_name,
            contextual_rag_llm_provider=search_settings.contextual_rag_llm_provider,
            # Reranking Details
            rerank_model_name=search_settings.rerank_model_name,
            rerank_provider_type=search_settings.rerank_provider_type,
            rerank_api_key=search_settings.rerank_api_key,
            num_rerank=search_settings.num_rerank,
            # Multilingual Expansion
            multilingual_expansion=search_settings.multilingual_expansion,
            rerank_api_url=search_settings.rerank_api_url,
            disable_rerank_for_streaming=search_settings.disable_rerank_for_streaming,
        )


class Tag(BaseModel):
    tag_key: str
    tag_value: str


class BaseFilters(BaseModel):
    source_type: list[DocumentSource] | None = None
    document_set: list[str] | None = None
    time_cutoff: datetime | None = None
    tags: list[Tag] | None = None
    kg_entities: list[str] | None = None
    kg_relationships: list[str] | None = None
    kg_terms: list[str] | None = None
    kg_sources: list[str] | None = None
    kg_chunk_id_zero_only: bool | None = False


class UserFileFilters(BaseModel):
    user_file_ids: list[UUID] | None = None
    project_id: int | None = None


class IndexFilters(BaseFilters, UserFileFilters):
    access_control_list: list[str] | None
    tenant_id: str | None = None


class ChunkMetric(BaseModel):
    document_id: str
    chunk_content_start: str
    first_link: str | None
    score: float


class ChunkContext(BaseModel):
    # If not specified (None), picked up from Persona settings if there is space
    # if specified (even if 0), it always uses the specified number of chunks above and below
    chunks_above: int | None = None
    chunks_below: int | None = None
    full_doc: bool = False

    @field_validator("chunks_above", "chunks_below")
    @classmethod
    def check_non_negative(cls, value: int, field: Any) -> int:
        if value is not None and value < 0:
            raise ValueError(f"{field.name} must be non-negative")
        return value


class SearchRequest(ChunkContext):
    query: str

    expanded_queries: QueryExpansions | None = None
    original_query: str | None = None

    search_type: SearchType = SearchType.SEMANTIC

    human_selected_filters: BaseFilters | None = None
    user_file_filters: UserFileFilters | None = None
    enable_auto_detect_filters: bool | None = None
    persona: Persona | None = None

    # if None, no offset / limit
    offset: int | None = None
    limit: int | None = None

    multilingual_expansion: list[str] | None = None
    recency_bias_multiplier: float = 1.0
    hybrid_alpha: float | None = None
    rerank_settings: RerankingDetails | None = None
    evaluation_type: LLMEvaluationType = LLMEvaluationType.UNSPECIFIED
    model_config = ConfigDict(arbitrary_types_allowed=True)

    precomputed_query_embedding: Embedding | None = None
    precomputed_is_keyword: bool | None = None
    precomputed_keywords: list[str] | None = None


class SearchQuery(ChunkContext):
    "Processed Request that is directly passed to the SearchPipeline"

    query: str
    processed_keywords: list[str]
    search_type: SearchType
    evaluation_type: LLMEvaluationType
    filters: IndexFilters

    # by this point, the chunks_above and chunks_below must be set
    chunks_above: int
    chunks_below: int

    rerank_settings: RerankingDetails | None
    hybrid_alpha: float
    recency_bias_multiplier: float

    # Only used if LLM evaluation type is not skip, None to use default settings
    max_llm_filter_sections: int

    num_hits: int = NUM_RETURNED_HITS
    offset: int = 0
    model_config = ConfigDict(frozen=True)

    precomputed_query_embedding: Embedding | None = None

    expanded_queries: QueryExpansions | None = None
    original_query: str | None


class RetrievalDetails(ChunkContext):
    # Use LLM to determine whether to do a retrieval or only rely on existing history
    # If the Persona is configured to not run search (0 chunks), this is bypassed
    # If no Prompt is configured, the only search results are shown, this is bypassed
    run_search: OptionalSearchSetting = OptionalSearchSetting.ALWAYS
    # Is this a real-time/streaming call or a question where Onyx can take more time?
    # Used to determine reranking flow
    real_time: bool = True
    # The following have defaults in the Persona settings which can be overridden via
    # the query, if None, then use Persona settings
    filters: BaseFilters | None = None
    enable_auto_detect_filters: bool | None = None
    # if None, no offset / limit
    offset: int | None = None
    limit: int | None = None

    # If this is set, only the highest matching chunk (or merged chunks) is returned
    dedupe_docs: bool = False


class InferenceChunk(BaseChunk):
    document_id: str
    source_type: DocumentSource
    semantic_identifier: str
    title: str | None  # Separate from Semantic Identifier though often same
    boost: int
    recency_bias: float
    score: float | None
    hidden: bool
    is_relevant: bool | None = None
    relevance_explanation: str | None = None
    metadata: dict[str, str | list[str]]
    # Matched sections in the chunk. Uses Vespa syntax e.g. <hi>TEXT</hi>
    # to specify that a set of words should be highlighted. For example:
    # ["<hi>the</hi> <hi>answer</hi> is 42", "he couldn't find an <hi>answer</hi>"]
    match_highlights: list[str]
    doc_summary: str
    chunk_context: str

    # when the doc was last updated
    updated_at: datetime | None
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None
    large_chunk_reference_ids: list[int] = Field(default_factory=list)

    is_federated: bool = False

    @property
    def unique_id(self) -> str:
        return f"{self.document_id}__{self.chunk_id}"

    def __repr__(self) -> str:
        blurb_words = self.blurb.split()
        short_blurb = ""
        for word in blurb_words:
            if not short_blurb:
                short_blurb = word
                continue
            if len(short_blurb) > 25:
                break
            short_blurb += " " + word
        return f"Inference Chunk: {self.document_id} - {short_blurb}..."

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, InferenceChunk):
            return False
        return (self.document_id, self.chunk_id) == (other.document_id, other.chunk_id)

    def __hash__(self) -> int:
        return hash((self.document_id, self.chunk_id))

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, InferenceChunk):
            return NotImplemented
        if self.score is None:
            if other.score is None:
                return self.chunk_id > other.chunk_id
            return True
        if other.score is None:
            return False
        if self.score == other.score:
            return self.chunk_id > other.chunk_id
        return self.score < other.score

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, InferenceChunk):
            return NotImplemented
        if self.score is None:
            return False
        if other.score is None:
            return True
        if self.score == other.score:
            return self.chunk_id < other.chunk_id
        return self.score > other.score


class InferenceChunkUncleaned(InferenceChunk):
    metadata_suffix: str | None

    def to_inference_chunk(self) -> InferenceChunk:
        # Create a dict of all fields except 'metadata_suffix'
        # Assumes the cleaning has already been applied and just needs to translate to the right type
        inference_chunk_data = {
            k: v
            for k, v in self.model_dump().items()
            if k
            not in ["metadata_suffix"]  # May be other fields to throw out in the future
        }
        return InferenceChunk(**inference_chunk_data)


class InferenceSection(BaseModel):
    """Section list of chunks with a combined content. A section could be a single chunk, several
    chunks from the same document or the entire document."""

    center_chunk: InferenceChunk
    chunks: list[InferenceChunk]
    combined_content: str


class SearchDoc(BaseModel):
    document_id: str
    chunk_ind: int
    semantic_identifier: str
    link: str | None = None
    blurb: str
    source_type: DocumentSource
    boost: int
    # Whether the document is hidden when doing a standard search
    # since a standard search will never find a hidden doc, this can only ever
    # be `True` when doing an admin search
    hidden: bool
    metadata: dict[str, str | list[str]]
    score: float | None = None
    is_relevant: bool | None = None
    relevance_explanation: str | None = None
    # Matched sections in the doc. Uses Vespa syntax e.g. <hi>TEXT</hi>
    # to specify that a set of words should be highlighted. For example:
    # ["<hi>the</hi> <hi>answer</hi> is 42", "the answer is <hi>42</hi>""]
    match_highlights: list[str]
    # when the doc was last updated
    updated_at: datetime | None = None
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None
    is_internet: bool = False

    @classmethod
    def from_chunks_or_sections(
        cls,
        items: "Sequence[InferenceChunk | InferenceSection] | None",
    ) -> list["SearchDoc"]:
        """Convert a sequence of InferenceChunk or InferenceSection objects to SearchDoc objects."""
        if not items:
            return []

        search_docs = [
            cls(
                document_id=(
                    chunk := (
                        item.center_chunk
                        if isinstance(item, InferenceSection)
                        else item
                    )
                ).document_id,
                chunk_ind=chunk.chunk_id,
                semantic_identifier=chunk.semantic_identifier or "Unknown",
                link=chunk.source_links[0] if chunk.source_links else None,
                blurb=chunk.blurb,
                source_type=chunk.source_type,
                boost=chunk.boost,
                hidden=chunk.hidden,
                metadata=chunk.metadata,
                score=chunk.score,
                match_highlights=chunk.match_highlights,
                updated_at=chunk.updated_at,
                primary_owners=chunk.primary_owners,
                secondary_owners=chunk.secondary_owners,
                is_internet=False,
            )
            for item in items
        ]

        return search_docs

    def model_dump(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        initial_dict = super().model_dump(*args, **kwargs)  # type: ignore
        initial_dict["updated_at"] = (
            self.updated_at.isoformat() if self.updated_at else None
        )
        return initial_dict


class SavedSearchDoc(SearchDoc):
    db_doc_id: int
    score: float = 0.0

    @classmethod
    def from_search_doc(
        cls, search_doc: SearchDoc, db_doc_id: int = 0
    ) -> "SavedSearchDoc":
        """IMPORTANT: careful using this and not providing a db_doc_id If db_doc_id is not
        provided, it won't be able to actually fetch the saved doc and info later on. So only skip
        providing this if the SavedSearchDoc will not be used in the future"""
        search_doc_data = search_doc.model_dump()
        search_doc_data["score"] = search_doc_data.get("score") or 0.0
        return cls(**search_doc_data, db_doc_id=db_doc_id)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SavedSearchDoc":
        """Create SavedSearchDoc from serialized dictionary data (e.g., from database JSON)"""
        return cls(**data)

    @classmethod
    def from_url(cls, url: str) -> "SavedSearchDoc":
        """Create a SavedSearchDoc from a URL for internet search documents.

        Uses the INTERNET_SEARCH_DOC_ prefix for document_id to match the format
        used by inference sections created from internet content.
        """
        return cls(
            # db_doc_id can be a filler value since these docs are not saved to the database.
            db_doc_id=0,
            document_id="INTERNET_SEARCH_DOC_" + url,
            chunk_ind=0,
            semantic_identifier=url,
            link=url,
            blurb="",
            source_type=DocumentSource.WEB,
            boost=1,
            hidden=False,
            metadata={},
            score=0.0,
            is_relevant=None,
            relevance_explanation=None,
            match_highlights=[],
            updated_at=None,
            primary_owners=None,
            secondary_owners=None,
            is_internet=True,
        )

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, SavedSearchDoc):
            return NotImplemented
        return self.score < other.score


class SavedSearchDocWithContent(SavedSearchDoc):
    """Used for endpoints that need to return the actual contents of the retrieved
    section in addition to the match_highlights."""

    content: str


class RetrievalDocs(BaseModel):
    top_documents: list[SavedSearchDoc]


class SearchResponse(RetrievalDocs):
    llm_indices: list[int]


class RetrievalMetricsContainer(BaseModel):
    search_type: SearchType
    metrics: list[ChunkMetric]  # This contains the scores for retrieval as well


class RerankMetricsContainer(BaseModel):
    """The score held by this is the un-boosted, averaged score of the ensemble cross-encoders"""

    metrics: list[ChunkMetric]
    raw_similarity_scores: list[float]
