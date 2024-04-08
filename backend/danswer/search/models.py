from datetime import datetime
from typing import Any

from pydantic import BaseModel

from danswer.configs.chat_configs import DISABLE_LLM_CHUNK_FILTER
from danswer.configs.chat_configs import HYBRID_ALPHA
from danswer.configs.chat_configs import NUM_RERANKED_RESULTS
from danswer.configs.chat_configs import NUM_RETURNED_HITS
from danswer.configs.constants import DocumentSource
from danswer.db.models import Persona
from danswer.search.enums import OptionalSearchSetting
from danswer.search.enums import SearchType
from shared_configs.nlp_model_configs import ENABLE_RERANKING_REAL_TIME_FLOW


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


class SearchRequest(BaseModel):
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


class SearchQuery(BaseModel):
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


class RetrievalDetails(BaseModel):
    # Use LLM to determine whether to do a retrieval or only rely on existing history
    # If the Persona is configured to not run search (0 chunks), this is bypassed
    # If no Prompt is configured, the only search results are shown, this is bypassed
    run_search: OptionalSearchSetting = OptionalSearchSetting.ALWAYS
    # Is this a real-time/streaming call or a question where Danswer can take more time?
    # Used to determine reranking flow
    real_time: bool = True
    # The following have defaults in the Persona settings which can be overriden via
    # the query, if None, then use Persona settings
    filters: BaseFilters | None = None
    enable_auto_detect_filters: bool | None = None
    # if None, no offset / limit
    offset: int | None = None
    limit: int | None = None


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
