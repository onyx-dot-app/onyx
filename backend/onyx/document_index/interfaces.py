import abc
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from onyx.access.models import DocumentAccess
from onyx.access.models import ExternalAccess
from onyx.agents.agent_search.shared_graph_utils.models import QueryExpansionType
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.db.enums import EmbeddingPrecision
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.model_server_models import Embedding


@dataclass(frozen=True)
class DocumentInsertionRecord:
    document_id: str
    already_existed: bool


@dataclass(frozen=True)
class VespaChunkRequest:
    document_id: str
    min_chunk_ind: int | None = None
    max_chunk_ind: int | None = None

    @property
    def is_capped(self) -> bool:
        # If the max chunk index is not None, then the chunk request is capped
        # If the min chunk index is None, we can assume the min is 0
        return self.max_chunk_ind is not None

    @property
    def range(self) -> int | None:
        if self.max_chunk_ind is not None:
            return (self.max_chunk_ind - (self.min_chunk_ind or 0)) + 1
        return None


@dataclass
class IndexBatchParams:
    """
    Information necessary for efficiently indexing a batch of documents
    """

    doc_id_to_previous_chunk_cnt: dict[str, int]
    doc_id_to_new_chunk_cnt: dict[str, int]
    tenant_id: str
    large_chunks_enabled: bool


@dataclass
class MinimalDocumentIndexingInfo:
    """
    Minimal information necessary for indexing a document
    """

    doc_id: str
    chunk_start_index: int


@dataclass
class EnrichedDocumentIndexingInfo(MinimalDocumentIndexingInfo):
    """
    Enriched information necessary for indexing a document, including version and chunk range.
    """

    old_version: bool
    chunk_end_index: int


@dataclass
class DocumentMetadata:
    """
    Document information that needs to be inserted into Postgres on first time encountering this
    document during indexing across any of the connectors.
    """

    connector_id: int
    credential_id: int
    document_id: str
    semantic_identifier: str
    first_link: str
    doc_updated_at: datetime | None = None
    # Emails, not necessarily attached to users
    # Users may not be in Onyx
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None
    from_ingestion_api: bool = False

    external_access: ExternalAccess | None = None
    doc_metadata: dict[str, Any] | None = None


@dataclass
class VespaDocumentFields:
    """
    Specifies fields in Vespa for a document.  Fields set to None will be ignored.
    Perhaps we should name this in an implementation agnostic fashion, but it's more
    understandable like this for now.
    """

    # all other fields except these 4 will always be left alone by the update request
    access: DocumentAccess | None = None
    document_sets: set[str] | None = None
    boost: float | None = None
    hidden: bool | None = None
    aggregated_chunk_boost_factor: float | None = None

    # document_id is added for migration purposes, ideally we should not be updating this field
    # TODO(subash): remove this field in a future migration
    document_id: str | None = None


@dataclass
class VespaDocumentUserFields:
    """
    Fields that are specific to the user who is indexing the document.
    """

    user_projects: list[int] | None = None


@dataclass
class UpdateRequest:
    """
    For all document_ids, update the allowed_users and the boost to the new values
    Does not update any of the None fields
    """

    minimal_document_indexing_info: list[MinimalDocumentIndexingInfo]
    # all other fields except these 4 will always be left alone by the update request
    access: DocumentAccess | None = None
    document_sets: set[str] | None = None
    boost: float | None = None
    hidden: bool | None = None


class Verifiable(abc.ABC):
    """
    Class must implement document index schema verification. For example, verify that all of the
    necessary attributes for indexing, querying, filtering, and fields to return from search are
    all valid in the schema.

    Parameters:
    - index_name: The name of the primary index currently used for querying
    - secondary_index_name: The name of the secondary index being built in the background, if it
            currently exists. Some functions on the document index act on both the primary and
            secondary index, some act on just one.
    """

    @abc.abstractmethod
    def __init__(
        self,
        index_name: str,
        secondary_index_name: str | None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.index_name = index_name
        self.secondary_index_name = secondary_index_name

    @abc.abstractmethod
    def ensure_indices_exist(
        self,
        primary_embedding_dim: int,
        primary_embedding_precision: EmbeddingPrecision,
        secondary_index_embedding_dim: int | None,
        secondary_index_embedding_precision: EmbeddingPrecision | None,
    ) -> None:
        """
        Verify that the document index exists and is consistent with the expectations in the code.

        Parameters:
        - primary_embedding_dim: Vector dimensionality for the vector similarity part of the search
        - primary_embedding_precision: Precision of the vector similarity part of the search
        - secondary_index_embedding_dim: Vector dimensionality of the secondary index being built
                behind the scenes. The secondary index should only be built when switching
                embedding models therefore this dim should be different from the primary index.
        - secondary_index_embedding_precision: Precision of the vector similarity part of the secondary index
        """
        raise NotImplementedError

    @staticmethod
    @abc.abstractmethod
    def register_multitenant_indices(
        indices: list[str],
        embedding_dims: list[int],
        embedding_precisions: list[EmbeddingPrecision],
    ) -> None:
        """
        Register multitenant indices with the document index.
        """
        raise NotImplementedError


class Indexable(abc.ABC):
    """
    Class must implement the ability to index document chunks
    """

    @abc.abstractmethod
    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        index_batch_params: IndexBatchParams,
    ) -> set[DocumentInsertionRecord]:
        """
        Takes a list of document chunks and indexes them in the document index

        NOTE: When a document is reindexed/updated here, it must clear all of the existing document
        chunks before reindexing. This is because the document may have gotten shorter since the
        last run. Therefore, upserting the first 0 through n chunks may leave some old chunks that
        have not been written over.

        NOTE: The chunks of a document are never separated into separate index() calls. So there is
        no worry of receiving the first 0 through n chunks in one index call and the next n through
        m chunks of a docu in the next index call.

        NOTE: Due to some asymmetry between the primary and secondary indexing logic, this function
        only needs to index chunks into the PRIMARY index. Do not update the secondary index here,
        it is done automatically outside of this code.

        Parameters:
        - chunks: Document chunks with all of the information needed for indexing to the document
                index.
        - tenant_id: The tenant id of the user whose chunks are being indexed
        - large_chunks_enabled: Whether large chunks are enabled

        Returns:
            List of document ids which map to unique documents and are used for deduping chunks
            when updating, as well as if the document is newly indexed or already existed and
            just updated
        """
        raise NotImplementedError


class Deletable(abc.ABC):
    """
    Class must implement the ability to delete document by a given unique document id.
    """

    @abc.abstractmethod
    def delete_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
    ) -> int:
        """
        Given a single document id, hard delete it from the document index

        Parameters:
        - doc_id: document id as specified by the connector
        """
        raise NotImplementedError


class Updatable(abc.ABC):
    """
    Class must implement the ability to update certain attributes of a document without needing to
    update all of the fields. Specifically, needs to be able to update:
    - Access Control List
    - Document-set membership
    - Boost value (learning from feedback mechanism)
    - Whether the document is hidden or not, hidden documents are not returned from search
    """

    @abc.abstractmethod
    def update_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> int:
        """
        Updates all chunks for a document with the specified fields.
        None values mean that the field does not need an update.

        The rationale for a single update function is that it allows retries and parallelism
        to happen at a higher / more strategic level, is simpler to read, and allows
        us to individually handle error conditions per document.

        Parameters:
        - fields: the fields to update in the document. Any field set to None will not be changed.

        Return:
            None
        """
        raise NotImplementedError

    @abc.abstractmethod
    def update(self, update_requests: list[UpdateRequest], *, tenant_id: str) -> None:
        """
        Updates some set of chunks. The document and fields to update are specified in the update
        requests. Each update request in the list applies its changes to a list of document ids.
        None values mean that the field does not need an update.

        Parameters:
        - update_requests: for a list of document ids in the update request, apply the same updates
                to all of the documents with those ids. This is for bulk handling efficiency. Many
                updates are done at the connector level which have many documents for the connector
        """
        raise NotImplementedError


class IdRetrievalCapable(abc.ABC):
    """
    Class must implement the ability to retrieve either:
    - all of the chunks of a document IN ORDER given a document id.
    - a specific chunk given a document id and a chunk index (0 based)
    """

    @abc.abstractmethod
    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
    ) -> list[InferenceChunkUncleaned]:
        """
        Fetch chunk(s) based on document id

        NOTE: This is used to reconstruct a full document or an extended (multi-chunk) section
        of a document. Downstream currently assumes that the chunking does not introduce overlaps
        between the chunks. If there are overlaps for the chunks, then the reconstructed document
        or extended section will have duplicate segments.

        Parameters:
        - chunk_requests: requests containing the document id and the chunk range to retrieve
        - filters: Filters to apply to retrieval
        - batch_retrieval: If True, perform a batch retrieval

        Returns:
            list of chunks for the document id or the specific chunk by the specified chunk index
            and document id
        """
        raise NotImplementedError


class HybridCapable(abc.ABC):
    """
    Class must implement hybrid (keyword + vector) search functionality
    """

    @abc.abstractmethod
    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        filters: IndexFilters,
        hybrid_alpha: float,
        time_decay_multiplier: float,
        num_to_retrieve: int,
        ranking_profile_type: QueryExpansionType,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
    ) -> list[InferenceChunkUncleaned]:
        """
        Run hybrid search and return a list of inference chunks.

        NOTE: the query passed in here is the unprocessed plain text query. Preprocessing is
        expected to be handled by this function as it may depend on the index implementation.
        Things like query expansion, synonym injection, stop word removal, lemmatization, etc. are
        done here.

        Parameters:
        - query: unmodified user query. This is needed for getting the matching highlighted
                keywords
        - query_embedding: vector representation of the query, must be of the correct
                dimensionality for the primary index
        - final_keywords: Final keywords to be used from the query, defaults to query if not set
        - filters: standard filter object
        - hybrid_alpha: weighting between the keyword and vector search results. It is important
                that the two scores are normalized to the same range so that a meaningful
                comparison can be made. 1 for 100% weighting on vector score, 0 for 100% weighting
                on keyword score.
        - time_decay_multiplier: how much to decay the document scores as they age. Some queries
                based on the persona settings, will have this be a 2x or 3x of the default
        - num_to_retrieve: number of highest matching chunks to return
        - offset: number of highest matching chunks to skip (kind of like pagination)

        Returns:
            best matching chunks based on weighted sum of keyword and vector/semantic search scores
        """
        raise NotImplementedError


class AdminCapable(abc.ABC):
    """
    Class must implement a search for the admin "Explorer" page. The assumption here is that the
    admin is not "searching" for knowledge but has some document already in mind. They are either
    looking to positively boost it because they know it's a good reference document, looking to
    negatively boost it as a way of "deprecating", or hiding the document.

    Assuming the admin knows the document name, this search has high emphasis on the title match.

    Suggested implementation:
    Keyword only, BM25 search with 5x weighting on the title field compared to the contents
    """

    @abc.abstractmethod
    def admin_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int,
        offset: int = 0,
    ) -> list[InferenceChunkUncleaned]:
        """
        Run the special search for the admin document explorer page

        Parameters:
        - query: unmodified user query. Though in this flow probably unmodified is best
        - filters: standard filter object
        - num_to_retrieve: number of highest matching chunks to return
        - offset: number of highest matching chunks to skip (kind of like pagination)

        Returns:
            list of best matching chunks for the explorer page query
        """
        raise NotImplementedError


class RandomCapable(abc.ABC):
    """Class must implement random document retrieval capability"""

    @abc.abstractmethod
    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
    ) -> list[InferenceChunkUncleaned]:
        """Retrieve random chunks matching the filters"""
        raise NotImplementedError


class BaseIndex(
    Verifiable,
    Indexable,
    Updatable,
    Deletable,
    AdminCapable,
    IdRetrievalCapable,
    RandomCapable,
    abc.ABC,
):
    """
    All basic document index functionalities excluding the actual querying approach.

    As a summary, document indices need to be able to
    - Verify the schema definition is valid
    - Index new documents
    - Update specific attributes of existing documents
    - Delete documents
    - Provide a search for the admin document explorer page
    - Retrieve documents based on document id
    """


class DocumentIndex(HybridCapable, BaseIndex, abc.ABC):
    """
    A valid document index that can plug into all Onyx flows must implement all of these
    functionalities, though "technically" it does not need to be keyword or vector capable as
    currently all default search flows use Hybrid Search.
    """
