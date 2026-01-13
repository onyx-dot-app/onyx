import abc
from typing import Self

from pydantic import BaseModel
from pydantic import model_validator

from onyx.access.models import DocumentAccess
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.db.enums import EmbeddingPrecision
from onyx.document_index.opensearch.constants import DEFAULT_MAX_CHUNK_SIZE
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.model_server_models import Embedding

# NOTE: "Document" in the naming convention is used to refer to the entire
# document as represented in Onyx. What is actually stored in the index is the
# document chunks. By the terminology of most search engines / vector databases,
# the individual objects stored are called documents, but in this case it refers
# to a chunk.


__all__ = [
    # Main interfaces - these are what you should inherit from
    "DocumentIndex",
    # Data models - used in method signatures
    "DocumentInsertionRecord",
    "DocumentSectionRequest",
    "IndexingMetadata",
    "MetadataUpdateRequest",
    # Capability mixins - for custom compositions or type checking
    "SchemaVerifiable",
    "Indexable",
    "Deletable",
    "Updatable",
    "IdRetrievalCapable",
    "HybridCapable",
    "RandomCapable",
]


class TenantState(BaseModel):
    """
    Captures the tenant-related state for an instance of DocumentIndex.

    NOTE: Tenant ID must be set in multitenant mode.
    """

    model_config = {"frozen": True}

    tenant_id: str
    multitenant: bool

    @model_validator(mode="after")
    def check_tenant_id_is_set_in_multitenant_mode(self) -> Self:
        if self.multitenant and not self.tenant_id:
            raise ValueError("Bug: Tenant ID must be set in multitenant mode.")
        return self


class DocumentInsertionRecord(BaseModel):
    """
    Result of indexing a document.
    """

    model_config = {"frozen": True}

    document_id: str
    already_existed: bool


class DocumentSectionRequest(BaseModel):
    """Request for a document section or whole document.

    If no min_chunk_ind is provided it should start at the beginning of the
    document.
    If no max_chunk_ind is provided it should go to the end of the document.
    """

    model_config = {"frozen": True}

    document_id: str
    min_chunk_ind: int | None = None
    max_chunk_ind: int | None = None
    # A given document can have multiple chunking strategies.
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE

    @model_validator(mode="after")
    def check_chunk_index_range_is_valid(self) -> Self:
        if (
            self.min_chunk_ind is not None
            and self.max_chunk_ind is not None
            and self.min_chunk_ind > self.max_chunk_ind
        ):
            raise ValueError(
                "Bug: Min chunk index must be less than or equal to max chunk index."
            )
        return self


class IndexingMetadata(BaseModel):
    """
    Information about chunk counts for efficient cleaning / updating of document
    chunks.

    A common pattern to ensure that no chunks are left over is to delete all of
    the chunks for a document and then re-index the document. This information
    allows us to only delete the extra "tail" chunks when the document has
    gotten shorter.
    """

    class ChunkCounts(BaseModel):
        model_config = {"frozen": True}

        old_chunk_cnt: int
        new_chunk_cnt: int

    model_config = {"frozen": True}

    doc_id_to_chunk_cnt_diff: dict[str, ChunkCounts]


class MetadataUpdateRequest(BaseModel):
    """
    Updates to the documents that can happen without there being an update to
    the contents of the document.
    """

    model_config = {"frozen": True}

    document_ids: list[str]
    # Passed in to help with potential optimizations of the implementation. The
    # keys should be redundant with document_ids.
    # NOTE: Generally the chunk count should always be known, however for
    # documents still using the legacy chunk ID system it may not be. Any chunk
    # count value < 0 should represent an unknown chunk count.
    doc_id_to_chunk_cnt: dict[str, int]
    # For the ones that are None, there is no update required to that field.
    access: DocumentAccess | None = None
    document_sets: set[str] | None = None
    boost: float | None = None
    hidden: bool | None = None
    secondary_index_updated: bool | None = None
    project_ids: set[int] | None = None


class IndexRetrievalFilters(BaseModel):
    """
    Filters for retrieving chunks from the index.

    Used to filter on permissions and other Onyx-specific metadata rather than
    chunk content. Should be passed in for every retrieval method.

    TODO(andrei): Currently unused, use this when making retrieval methods more
    strict.
    """

    model_config = {"frozen": True}

    # frozenset gets around the issue of python's mutable defaults.
    # WARNING: Falls back to only public docs as default for security. If
    # callers want no access filtering they must explicitly supply an empty set.
    # Doing so should be done sparingly.
    access_control_list: frozenset[str] = frozenset({PUBLIC_DOC_PAT})


class SchemaVerifiable(abc.ABC):
    """
    Class must implement document index schema verification. For example, verify that all of the
    necessary attributes for indexing, querying, filtering, and fields to return from search are
    all valid in the schema.
    """

    @abc.abstractmethod
    def verify_and_create_index_if_necessary(
        self,
        embedding_dim: int,
        embedding_precision: EmbeddingPrecision,
    ) -> None:
        """
        Verify that the document index exists and is consistent with the expectations in the code. For certain search
        engines, the schema needs to be created before indexing can happen. This call should create the schema if it
        does not exist.

        Parameters:
        - embedding_dim: Vector dimensionality for the vector similarity part of the search
        - embedding_precision: Precision of the vector similarity part of the search
        """
        raise NotImplementedError


class Indexable(abc.ABC):
    """
    Class must implement the ability to index document chunks.
    """

    @abc.abstractmethod
    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        """Indexes a list of document chunks into the document index.

        This is often a batch operation including chunks from multiple
        documents.

        NOTE: When a document is reindexed/updated here and has gotten shorter,
        it is important to delete the extra chunks at the end to ensure there
        are no stale chunks in the index. The implementation should do this.

        NOTE: The chunks of a document are never separated into separate index()
        calls. So there is no worry of receiving the first 0 through n chunks in
        one index call and the next n through m chunks of a document in the next
        index call.

        Args:
            chunks: Document chunks with all of the information needed for
                indexing to the document index.
            indexing_metadata: Information about chunk counts for efficient
                cleaning / updating.

        Returns:
            List of document IDs which map to unique documents as well as if the
                document is newly indexed or had already existed and was just
                updated.
        """
        raise NotImplementedError


class Deletable(abc.ABC):
    """
    Class must implement the ability to delete a document by a given unique
    document ID.
    """

    @abc.abstractmethod
    def delete(
        self,
        # TODO(andrei): Fine for now but this can probably be a batch operation that
        # takes in a list of IDs.
        document_id: str,
        chunk_count: int | None = None,
        # TODO(andrei): Shouldn't this also have some acl filtering at minimum?
    ) -> int:
        """
        Hard deletes all of the chunks for the corresponding document in the
        document index.

        TODO(andrei): Not a pressing issue now but think about what we want the
        contract of this method to be in the event the specified document ID
        does not exist.

        Args:
            document_id: The unique identifier for the document as represented
                in Onyx, not necessarily in the document index.
            chunk_count: The number of chunks in the document. May be useful for
                improving the efficiency of the delete operation. Defaults to
                None.

        Returns:
            The number of chunks deleted.
        """
        raise NotImplementedError


class Updatable(abc.ABC):
    """
    Class must implement the ability to update certain attributes of a document
    without needing to update all of the fields. Specifically, needs to be able
    to update:
    - Access Control List
    - Document-set membership
    - Boost value (learning from feedback mechanism)
    - Whether the document is hidden or not; hidden documents are not returned
      from search
    - Which Projects the document is a part of
    """

    @abc.abstractmethod
    def update(
        self,
        update_requests: list[MetadataUpdateRequest],
    ) -> None:
        """
        Updates some set of chunks. The document and fields to update are specified in the update
        requests. Each update request in the list applies its changes to a list of document ids.
        None values mean that the field does not need an update.

        The document and fields to update are specified in the update requests.
        Each update request in the list applies its changes to a list of
        document IDs. None values mean that the field does not need an update.

        Args:
            update_requests: A list of update requests, each containing a list
                of document IDs and the fields to update. The field updates
                apply to all of the specified documents in each update request.
        """
        raise NotImplementedError


class IdRetrievalCapable(abc.ABC):
    """
    Class must implement the ability to retrieve either:
    - All of the chunks of a document IN ORDER given a document ID.
    - A specific section (continuous set of chunks) for some document.
    """

    @abc.abstractmethod
    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        # TODO(andrei): Make this more strict w.r.t. acl, temporary for now.
        filters: IndexFilters,
        # TODO(andrei): This is temporary, we will not expose this in the long
        # run.
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        """Fetches chunk(s) based on document ID.

        NOTE: This is used to reconstruct a full document or an extended
        (multi-chunk) section of a document. Downstream currently assumes that
        the chunking does not introduce overlaps between the chunks. If there
        are overlaps for the chunks, then the reconstructed document or extended
        section will have duplicate segments.

        Args:
            chunk_requests: Requests containing the document ID and the chunk
                range to retrieve.

        Returns:
            List of sections from the documents specified.
        """
        raise NotImplementedError


class HybridCapable(abc.ABC):
    """
    Class must implement hybrid (keyword + vector) search functionality.
    """

    @abc.abstractmethod
    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        query_type: QueryType,
        # TODO(andrei): Make this more strict w.r.t. acl, temporary for now.
        filters: IndexFilters,
        num_to_retrieve: int,
        offset: int = 0,
    ) -> list[InferenceChunk]:
        """Runs hybrid search and returns a list of inference chunks.

        Args:
            query: Unmodified user query. This may be needed for getting the
                matching highlighted keywords or for logging purposes.
            query_embedding: Vector representation of the query. Must be of the
                correct dimensionality for the primary index.
            final_keywords: Final keywords to be used from the query; defaults
                to query if not set.
            query_type: Semantic or keyword type query; may use different
                scoring logic for each.
            filters: Filters for things like permissions, source type, time,
                etc.
            num_to_retrieve: Number of highest matching chunks to return.
            offset: Number of highest matching chunks to initially skip (kind of
                like pagination). Defaults to 0.

        Returns:
            Score-ranked (highest first) list of highest matching chunks.
        """
        raise NotImplementedError


class RandomCapable(abc.ABC):
    """
    Class must implement random document retrieval.

    This currently is just used for porting the documents to a secondary index.
    """

    @abc.abstractmethod
    def random_retrieval(
        self,
        # TODO(andrei): Make this more strict w.r.t. acl, temporary for now.
        filters: IndexFilters,
        num_to_retrieve: int = 100,
        dirty: bool | None = None,
    ) -> list[InferenceChunk]:
        """Retrieves random chunks matching the filters.

        Args:
            filters: Filters for things like permissions, source type, time,
                etc.
            num_to_retrieve: Number of chunks to retrieve. Defaults to 100.
            dirty: If set, retrieve chunks whose "dirty" flag matches this
                argument. If None, there is no restriction on retrieved chunks
                with respect to that flag. A chunk is considered dirty if there
                is a secondary index but the chunk's state has not been ported
                over to it yet. Defaults to None.

        Returns:
            List of chunks matching the filters.
        """
        raise NotImplementedError


class DocumentIndex(
    SchemaVerifiable,
    Indexable,
    Updatable,
    Deletable,
    HybridCapable,
    IdRetrievalCapable,
    RandomCapable,
    abc.ABC,
):
    """
    A valid document index that can plug into all Onyx flows must implement all
    of these functionalities.

    As a high-level summary, document indices need to be able to:
    - Verify the schema definition is valid
    - Index new documents
    - Update specific attributes of existing documents
    - Delete documents
    - Run hybrid search
    - Retrieve document or sections of documents based on document id
    - Retrieve sets of random documents
    """
