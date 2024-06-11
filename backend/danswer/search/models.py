from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import validator

from danswer.configs.chat_configs import DISABLE_LLM_CHUNK_FILTER
from danswer.configs.chat_configs import HYBRID_ALPHA
from danswer.configs.chat_configs import NUM_RERANKED_RESULTS
from danswer.configs.chat_configs import NUM_RETURNED_HITS
from danswer.configs.constants import DocumentSource
from danswer.db.models import Persona
from danswer.indexing.models import BaseChunk
from danswer.search.enums import OptionalSearchSetting
from danswer.search.enums import SearchType
from shared_configs.configs import ENABLE_RERANKING_REAL_TIME_FLOW


MAX_METRICS_CONTENT = (
    200  # Just need enough characters to identify where in the doc the chunk is
)


class Tag(BaseModel):
    tag_key: str
    tag_value: str


class BaseFilters(BaseModel):
    source_type: list[DocumentSource] | None = None
    document_set: list[str] | None = None
    time_cutoff: datetime | None = None
    tags: list[Tag] | None = None


class IndexFilters(BaseFilters):
    access_control_list: list[str] | None


class ChunkMetric(BaseModel):
    document_id: str
    chunk_content_start: str
    first_link: str | None
    score: float


class ChunkContext(BaseModel):
    # Additional surrounding context options, if full doc, then chunks are deduped
    # If surrounding context overlap, it is combined into one
    chunks_above: int = 0
    chunks_below: int = 0
    full_doc: bool = False

    @validator("chunks_above", "chunks_below", pre=True, each_item=False)
    def check_non_negative(cls, value: int, field: Any) -> int:
        if value < 0:
            raise ValueError(f"{field.name} must be non-negative")
        return value


class SearchRequest(ChunkContext):
    """Input to the SearchPipeline."""

    query: str
    search_type: SearchType = SearchType.HYBRID

    human_selected_filters: BaseFilters | None = None
    enable_auto_detect_filters: bool | None = None
    persona: Persona | None = None

    # if None, no offset / limit
    offset: int | None = None
    limit: int | None = None

    recency_bias_multiplier: float = 1.0
    hybrid_alpha: float = HYBRID_ALPHA
    # This is to forcibly skip (or run) the step, if None it uses the system defaults
    skip_rerank: bool | None = None
    skip_llm_chunk_filter: bool | None = None

    class Config:
        arbitrary_types_allowed = True


class SearchQuery(ChunkContext):
    query: str
    filters: IndexFilters
    recency_bias_multiplier: float
    num_hits: int = NUM_RETURNED_HITS
    offset: int = 0
    search_type: SearchType = SearchType.HYBRID
    skip_rerank: bool = not ENABLE_RERANKING_REAL_TIME_FLOW
    skip_llm_chunk_filter: bool = DISABLE_LLM_CHUNK_FILTER
    # Only used if not skip_rerank
    num_rerank: int | None = NUM_RERANKED_RESULTS
    # Only used if not skip_llm_chunk_filter
    max_llm_filter_chunks: int = NUM_RERANKED_RESULTS

    class Config:
        frozen = True


class RetrievalDetails(ChunkContext):
    # Use LLM to determine whether to do a retrieval or only rely on existing history
    # If the Persona is configured to not run search (0 chunks), this is bypassed
    # If no Prompt is configured, the only search results are shown, this is bypassed
    run_search: OptionalSearchSetting = OptionalSearchSetting.ALWAYS
    # Is this a real-time/streaming call or a question where Danswer can take more time?
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
    boost: int
    recency_bias: float
    score: float | None
    hidden: bool
    metadata: dict[str, str | list[str]]
    # Matched sections in the chunk. Uses Vespa syntax e.g. <hi>TEXT</hi>
    # to specify that a set of words should be highlighted. For example:
    # ["<hi>the</hi> <hi>answer</hi> is 42", "he couldn't find an <hi>answer</hi>"]
    match_highlights: list[str]
    # when the doc was last updated
    updated_at: datetime | None
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None

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


class InferenceSection(InferenceChunk):
    """Section is a combination of chunks. A section could be a single chunk, several consecutive
    chunks or the entire document"""

    combined_content: str

    @classmethod
    def from_chunk(
        cls, inf_chunk: InferenceChunk, content: str | None = None
    ) -> "InferenceSection":
        inf_chunk_data = inf_chunk.dict()
        return cls(**inf_chunk_data, combined_content=content or inf_chunk.content)


class SearchDoc(BaseModel):
    document_id: str
    chunk_ind: int
    semantic_identifier: str
    link: str | None
    blurb: str
    source_type: DocumentSource
    boost: int
    # Whether the document is hidden when doing a standard search
    # since a standard search will never find a hidden doc, this can only ever
    # be `True` when doing an admin search
    hidden: bool
    metadata: dict[str, str | list[str]]
    score: float | None
    # Matched sections in the doc. Uses Vespa syntax e.g. <hi>TEXT</hi>
    # to specify that a set of words should be highlighted. For example:
    # ["<hi>the</hi> <hi>answer</hi> is 42", "the answer is <hi>42</hi>""]
    match_highlights: list[str]
    # when the doc was last updated
    updated_at: datetime | None
    primary_owners: list[str] | None
    secondary_owners: list[str] | None

    def dict(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        initial_dict = super().dict(*args, **kwargs)  # type: ignore
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
        search_doc_data = search_doc.dict()
        search_doc_data["score"] = search_doc_data.get("score") or 0.0
        return cls(**search_doc_data, db_doc_id=db_doc_id)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, SavedSearchDoc):
            return NotImplemented
        return self.score < other.score


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
