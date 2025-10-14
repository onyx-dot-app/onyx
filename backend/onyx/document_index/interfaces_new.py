import abc
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from onyx.access.models import DocumentAccess
from onyx.access.models import ExternalAccess
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.db.enums import EmbeddingPrecision
from onyx.indexing.models import DocMetadataAwareIndexChunk
from shared_configs.model_server_models import Embedding

# NOTE: "Document" in the naming convention is used to refer to the entire document as represented in Onyx.
# What is actually stored in the index is the document chunks. By the terminology of most search engines / vector
# databases, the individual objects stored are called documents, but in this case it refers to a chunk.


class DocumentInsertionRecord(BaseModel):
    """
    Result of indexing a document
    """

    model_config = {"frozen": True}

    document_id: str
    already_existed: bool


class DocumentSectionRequest(BaseModel):
    """
    Request for a document section or whole document
    If no min_chunk_ind is provided it should start at the beginning of the document
    If no max_chunk_ind is provided it should go to the end of the document
    """

    model_config = {"frozen": True}

    document_id: str
    min_chunk_ind: int | None = None
    max_chunk_ind: int | None = None


class IndexingMetadata(BaseModel):
    """
    Information about chunk counts for efficient cleaning / updating of document chunks. A common pattern to ensure
    that no chunks are left over is to delete all of the chunks for a document and then re-index the document. This
    information allows us to only delete the extra "tail" chunks when the document has gotten shorter.
    """

    doc_id_to_old_chunk_cnt: dict[str, int]
    doc_id_to_new_chunk_cnt: dict[str, int]
    large_chunks_enabled: bool  # Meaning larger chunks should also get deleted


class DocumentMetadata(BaseModel):
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
    # Emails, not necessarily attached to users. Users may not be in Onyx.
    primary_owners: list[str] | None = None
    secondary_owners: list[str] | None = None
    from_ingestion_api: bool = False

    external_access: ExternalAccess | None = None
    doc_metadata: dict[str, Any] | None = None


class UserProjects(BaseModel):
    """
    Used by the Projects feature. Documents added to projects must also be indexed for RAG.
    """

    user_project_ids: list[int] | None = None


class MetadataUpdateRequest(BaseModel):
    """
    Updates to the documents that can happen without there being an update to the contents of the document.
    """

    document_ids: list[str]
    doc_id_to_chunk_cnt: dict[str, int]
    access: DocumentAccess | None = None
    document_sets: set[str] | None = None
    boost: float | None = None
    hidden: bool | None = None


class Verifiable(abc.ABC):
    """
    Class must implement document index schema verification. For example, verify that all of the
    necessary attributes for indexing, querying, filtering, and fields to return from search are
    all valid in the schema.
    """

    @abc.abstractmethod
    def __init__(
        self,
        index_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.index_name: str = index_name

    @abc.abstractmethod
    def ensure_indices_exist(
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
    Class must implement the ability to index document chunks
    """

    @abc.abstractmethod
    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> set[DocumentInsertionRecord]:
        """
        Takes a list of document chunks and indexes them in the document index. This is often a batch operation
        including chunks from multiple documents.

        NOTE: When a document is reindexed/updated here, it must clear all of the existing document
        chunks before reindexing. This is because the document may have gotten shorter since the
        last run. Therefore, upserting the first 0 through n chunks may leave some old chunks that
        have not been written over.

        NOTE: The chunks of a document are never separated into separate index() calls. So there is
        no worry of receiving the first 0 through n chunks in one index call and the next n through
        m chunks of a document in the next index call.

        Parameters:
        - chunks: Document chunks with all of the information needed for indexing to the document
                index.
        - indexing_metadata: Information about chunk counts for efficient cleaning / updating

        Returns:
            List of document ids which map to unique documents and are used for deduping chunks
            when updating, as well as if the document is newly indexed or already existed and
            just updated
        """
        raise NotImplementedError


class Deletable(abc.ABC):
    """
    Class must implement the ability to delete document by a given unique document id. Note that the document id is the
    unique identifier for the document as represented in Onyx, not in the document index.
    """

    @abc.abstractmethod
    def delete(
        self,
        doc_id: str,
        *,
        # Passed in in case it helps the efficiency of the delete implementation
        chunk_count: int | None,
    ) -> int:
        """
        Given a single document, hard delete all of the chunks for the document from the document index

        Parameters:
        - doc_id: document id as represented in Onyx
        - chunk_count: number of chunks in the document

        Returns:
            number of chunks deleted
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
    def update(self, update_requests: list[MetadataUpdateRequest]) -> None:
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
    - All of the chunks of a document IN ORDER given a document id. Caller assumes it to be in order.
    - A specific section (continuous set of chunks) for some document.
    """

    @abc.abstractmethod
    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
    ) -> list[InferenceChunk]:
        """
        Fetch chunk(s) based on document id

        NOTE: This is used to reconstruct a full document or an extended (multi-chunk) section
        of a document. Downstream currently assumes that the chunking does not introduce overlaps
        between the chunks. If there are overlaps for the chunks, then the reconstructed document
        or extended section will have duplicate segments.

        NOTE: This should be used after a search call to get more context around returned chunks.
        There is no filters here since the calling code should not be calling this on arbitrary
        documents.

        Parameters:
        - chunk_requests: requests containing the document id and the chunk range to retrieve

        Returns:
            list of sections from the documents specified
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
        query_type: QueryType,
        filters: IndexFilters,
        num_to_retrieve: int,
        offset: int = 0,
    ) -> list[InferenceChunk]:
        """
        Run hybrid search and return a list of inference chunks.

        NOTE: the query passed in here is the unprocessed plain text query. Preprocessing is
        expected to be handled by this function as it may depend on the index implementation.
        Things like query expansion, synonym injection, stop word removal, lemmatization, etc. are
        done here.

        Parameters:
        - query: unmodified user query. This may be needed for getting the matching highlighted
                keywords
        - query_embedding: vector representation of the query, must be of the correct
                dimensionality for the primary index
        - final_keywords: Final keywords to be used from the query, defaults to query if not set
        - query_type: Semantic or keyword type query, may use different scoring logic for each
        - filters: Filters for things like permissions, source type, time, etc.
        - num_to_retrieve: number of highest matching chunks to return
        - offset: number of highest matching chunks to skip (kind of like pagination)

        Returns:
            Score ranked (highest first) list of highest matching chunks
        """
        raise NotImplementedError


class RandomCapable(abc.ABC):
    """Class must implement random document retrieval capability"""

    @abc.abstractmethod
    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
    ) -> list[InferenceChunk]:
        """Retrieve random chunks matching the filters"""
        raise NotImplementedError


class BaseIndex(
    Verifiable,
    Indexable,
    Updatable,
    Deletable,
    abc.ABC,
):
    """
    All basic document index functionalities excluding the actual querying approach.

    As a summary, document indices need to be able to
    - Verify the schema definition is valid
    - Index new documents
    - Update specific attributes of existing documents
    - Delete documents
    """


class DocumentIndex(
    HybridCapable, BaseIndex, IdRetrievalCapable, RandomCapable, abc.ABC
):
    """
    A valid document index that can plug into all Onyx flows must implement all of these
    functionalities.
    """
