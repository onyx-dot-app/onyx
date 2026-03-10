from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from pydantic import Field

from onyx.configs.constants import DocumentSource
from onyx.db.models import SearchSettings
from onyx.indexing.models import BaseChunk
from onyx.indexing.models import IndexingSetting
from onyx.tools.tool_implementations.web_search.models import WEB_SEARCH_PREFIX


class QueryExpansions(BaseModel):
    keywords_expansions: list[str] | None = None
    semantic_expansions: list[str] | None = None


class QueryExpansionType(Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


class SearchSettingsCreationRequest(IndexingSetting):
    @classmethod
    def from_db_model(
        cls, search_settings: SearchSettings
    ) -> "SearchSettingsCreationRequest":
        indexing_setting = IndexingSetting.from_db_model(search_settings)
        return cls(**indexing_setting.model_dump())


class SavedSearchSettings(IndexingSetting):
    # Previously this contained also Inference time settings. Keeping this wrapper class around
    # as there may again be inference time settings that may get added.
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
            switchover_type=search_settings.switchover_type,
            enable_contextual_rag=search_settings.enable_contextual_rag,
            contextual_rag_llm_name=search_settings.contextual_rag_llm_name,
            contextual_rag_llm_provider=search_settings.contextual_rag_llm_provider,
        )


class Tag(BaseModel):
    tag_key: str
    tag_value: str


class BaseFilters(BaseModel):
    source_type: list[DocumentSource] | None = None
    document_set: list[str] | None = None
    time_cutoff: datetime | None = None
    tags: list[Tag] | None = None


class UserFileFilters(BaseModel):
    user_file_ids: list[UUID] | None = None
    project_id: int | None = None
    persona_id: int | None = None


class AssistantKnowledgeFilters(BaseModel):
    """Filters for knowledge attached to an assistant (persona).

    These filters scope search to documents/folders explicitly attached
    to the assistant. When present, only documents matching these criteria
    are searched (in addition to ACL filtering).
    """

    # Document IDs explicitly attached to the assistant
    attached_document_ids: list[str] | None = None
    # Hierarchy node IDs (folders/spaces) attached to the assistant.
    # Matches chunks where ancestor_hierarchy_node_ids contains any of these.
    hierarchy_node_ids: list[int] | None = None


class IndexFilters(BaseFilters, UserFileFilters, AssistantKnowledgeFilters):
    # NOTE: These strings must be formatted in the same way as the output of
    # DocumentAccess::to_acl.
    access_control_list: list[str] | None
    tenant_id: str | None = None


class BasicChunkRequest(BaseModel):
    query: str

    # In case the caller wants to override the weighting between semantic and keyword search.
    hybrid_alpha: float | None = None

    # In case some queries favor recency more than other queries.
    recency_bias_multiplier: float = 1.0

    limit: int | None = None


class ChunkSearchRequest(BasicChunkRequest):
    # Final filters are calculated from these
    user_selected_filters: BaseFilters | None = None

    # Use with caution!
    bypass_acl: bool = False


# From the Chat Session we know what project (if any) this search should include
# From the user uploads and persona uploaded files, we know which of those to include
class ChunkIndexRequest(BasicChunkRequest):
    # Calculated final filters
    filters: IndexFilters

    query_keywords: list[str] | None = None


class ContextExpansionType(str, Enum):
    NOT_RELEVANT = "not_relevant"
    MAIN_SECTION_ONLY = "main_section_only"
    INCLUDE_ADJACENT_SECTIONS = "include_adjacent_sections"
    FULL_DOCUMENT = "full_document"


class InferenceChunk(BaseChunk):
    document_id: str
    source_type: DocumentSource
    semantic_identifier: str
    title: str | None  # Separate from Semantic Identifier though often same
    boost: int
    score: float | None
    hidden: bool
    is_relevant: bool | None = None
    relevance_explanation: str | None = None
    # TODO(andrei): Ideally we could improve this to where each value is just a
    # list of strings.
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

    # TODO - there is likely a way to clean this all up and not have the switch between these
    @classmethod
    def from_saved_search_doc(cls, saved_search_doc: "SavedSearchDoc") -> "SearchDoc":
        """Convert a SavedSearchDoc to SearchDoc by dropping the db_doc_id field."""
        saved_search_doc_data = saved_search_doc.model_dump()
        # Remove db_doc_id as it's not part of SearchDoc
        saved_search_doc_data.pop("db_doc_id", None)
        return cls(**saved_search_doc_data)

    @classmethod
    def from_saved_search_docs(
        cls, saved_search_docs: list["SavedSearchDoc"]
    ) -> list["SearchDoc"]:
        return [
            cls.from_saved_search_doc(saved_search_doc)
            for saved_search_doc in saved_search_docs
        ]

    def model_dump(self, *args: list, **kwargs: dict[str, Any]) -> dict[str, Any]:  # type: ignore
        initial_dict = super().model_dump(*args, **kwargs)  # type: ignore
        initial_dict["updated_at"] = (
            self.updated_at.isoformat() if self.updated_at else None
        )
        return initial_dict


class SearchDocsResponse(BaseModel):
    search_docs: list[SearchDoc]
    # Maps the citation number to the document id
    # Since these are no longer just links on the frontend but instead document cards, mapping it to the
    # document id is  the most staightforward way.
    citation_mapping: dict[int, str]

    # For cases where the frontend only needs to display a subset of the search docs
    # The whole list is typically still needed for later steps but this set should be saved separately
    displayed_docs: list[SearchDoc] | None = None


class SavedSearchDoc(SearchDoc):
    db_doc_id: int
    score: float | None = 0.0

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
            document_id=WEB_SEARCH_PREFIX + url,
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
        self_score = self.score if self.score is not None else 0.0
        other_score = other.score if other.score is not None else 0.0
        return self_score < other_score


class SavedSearchDocWithContent(SavedSearchDoc):
    """Used for endpoints that need to return the actual contents of the retrieved
    section in addition to the match_highlights."""

    content: str
