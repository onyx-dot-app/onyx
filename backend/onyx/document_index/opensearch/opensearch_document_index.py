import json
from collections.abc import Iterable
from typing import Any

from opensearchpy.helpers.errors import BulkIndexError

from onyx.access.models import DocumentAccess
from onyx.configs.app_configs import MAX_CHUNKS_PER_DOC_BATCH
from onyx.configs.app_configs import VERIFY_CREATE_OPENSEARCH_INDEX_ON_INIT_MT
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.connectors.models import convert_metadata_list_of_strings_to_dict
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.db.enums import EmbeddingPrecision
from onyx.db.models import DocumentSource
from onyx.document_index.chunk_content_enrichment import cleanup_content_for_chunks
from onyx.document_index.chunk_content_enrichment import (
    generate_enriched_content_for_chunk_text,
)
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import DocumentInsertionRecord
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.client import SearchHit
from onyx.document_index.opensearch.cluster_settings import OPENSEARCH_CLUSTER_SETTINGS
from onyx.document_index.opensearch.constants import OpenSearchSearchType
from onyx.document_index.opensearch.schema import ACCESS_CONTROL_LIST_FIELD_NAME
from onyx.document_index.opensearch.schema import CONTENT_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_SETS_FIELD_NAME
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentChunkWithoutVectors
from onyx.document_index.opensearch.schema import DocumentSchema
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.document_index.opensearch.schema import GLOBAL_BOOST_FIELD_NAME
from onyx.document_index.opensearch.schema import HIDDEN_FIELD_NAME
from onyx.document_index.opensearch.schema import PERSONAS_FIELD_NAME
from onyx.document_index.opensearch.schema import USER_PROJECTS_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.document_index.opensearch.search import (
    get_min_max_normalization_pipeline_name_and_config,
)
from onyx.document_index.opensearch.search import (
    get_normalization_pipeline_name_and_config,
)
from onyx.document_index.opensearch.search import (
    get_zscore_normalization_pipeline_name_and_config,
)
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import Document
from onyx.redis.lock_context import redis_shared_lock
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import remove_invalid_unicode_chars
from shared_configs.configs import MULTI_TENANT
from shared_configs.model_server_models import Embedding

logger = setup_logger(__name__)


VERIFY_INDEX_LOCK_TTL_S = 60
VERIFY_INDEX_LOCK_BLOCKING_TIMEOUT_S = 60


# Per-process cache of indices we've already verified/created/applied the
# mapping for. Used for the multi-tenant cloud codepath, which attempts to
# verify or create an index on DocumentIndex init since that deployment mode
# does not run setup on application start. This attempt can be expensive, and it
# only needs to happen at most once per process lifetime, since any changes to
# an index should always be correlated with a redeploy.
_verified_index_names_for_current_process: set[str] = set()


class ChunkCountNotFoundError(ValueError):
    """Raised when a document has no chunk count."""


class ChunkCountZeroError(ValueError):
    """Raised when a document has a chunk count of 0."""


def generate_opensearch_filtered_access_control_list(
    access: DocumentAccess,
) -> list[str]:
    """Generates an access control list with PUBLIC_DOC_PAT removed.

    In the OpenSearch schema this is represented by PUBLIC_FIELD_NAME.
    """
    access_control_list = access.to_acl()
    access_control_list.discard(PUBLIC_DOC_PAT)
    return list(access_control_list)


def set_cluster_state(client: OpenSearchClient) -> None:
    if not client.put_cluster_settings(settings=OPENSEARCH_CLUSTER_SETTINGS):
        logger.error(
            "Failed to put cluster settings. If the settings have never been set before, "
            "this may cause unexpected index creation when indexing documents into an "
            "index that does not exist, or may cause expected logs to not appear. If this "
            "is not the first time running Onyx against this instance of OpenSearch, these "
            "settings have likely already been set. Not taking any further action..."
        )
    min_max_normalization_pipeline_name, min_max_normalization_pipeline_config = (
        get_min_max_normalization_pipeline_name_and_config()
    )
    zscore_normalization_pipeline_name, zscore_normalization_pipeline_config = (
        get_zscore_normalization_pipeline_name_and_config()
    )
    client.create_search_pipeline(
        pipeline_id=min_max_normalization_pipeline_name,
        pipeline_body=min_max_normalization_pipeline_config,
    )
    client.create_search_pipeline(
        pipeline_id=zscore_normalization_pipeline_name,
        pipeline_body=zscore_normalization_pipeline_config,
    )


def _convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
    chunk: DocumentChunkWithoutVectors,
    score: float | None,
    highlights: dict[str, list[str]],
) -> InferenceChunkUncleaned:
    """
    Generates an inference chunk from an OpenSearch document chunk, its score,
    and its match highlights.

    Args:
        chunk: The document chunk returned by OpenSearch.
        score: The document chunk match score as calculated by OpenSearch. Only
            relevant for searches like hybrid search. It is acceptable for this
            value to be None for results from other queries like ID-based
            retrieval as a match score makes no sense in those contexts.
        highlights: Maps schema property name to a list of highlighted snippets
            with match terms wrapped in tags (e.g. "something <hi>keyword</hi>
            other thing").

    Returns:
        An Onyx inference chunk representation.
    """
    return InferenceChunkUncleaned(
        chunk_id=chunk.chunk_index,
        blurb=chunk.blurb,
        # Includes extra content prepended/appended during indexing.
        content=chunk.content,
        # When we read a string and turn it into a dict the keys will be
        # strings, but in this case they need to be ints.
        source_links=(
            {int(k): v for k, v in json.loads(chunk.source_links).items()}
            if chunk.source_links
            else None
        ),
        image_file_id=chunk.image_file_id,
        # Deprecated. Fill in some reasonable default.
        section_continuation=False,
        document_id=chunk.document_id,
        source_type=DocumentSource(chunk.source_type),
        semantic_identifier=chunk.semantic_identifier,
        title=chunk.title,
        boost=chunk.global_boost,
        score=score,
        hidden=chunk.hidden,
        metadata=(
            convert_metadata_list_of_strings_to_dict(chunk.metadata_list)
            if chunk.metadata_list
            else {}
        ),
        # Extract highlighted snippets from the content field, if available. In
        # the future we may want to match on other fields too, currently we only
        # use the content field.
        match_highlights=highlights.get(CONTENT_FIELD_NAME, []),
        # TODO(andrei) Consider storing a chunk content index instead of a full
        # string when working on chunk content augmentation.
        doc_summary=chunk.doc_summary,
        # TODO(andrei) Same thing as above.
        chunk_context=chunk.chunk_context,
        updated_at=chunk.last_updated,
        primary_owners=chunk.primary_owners,
        secondary_owners=chunk.secondary_owners,
        # TODO(andrei) Same thing as chunk_context above.
        metadata_suffix=chunk.metadata_suffix,
    )


def _convert_onyx_chunk_to_opensearch_document(
    chunk: DocMetadataAwareIndexChunk,
) -> DocumentChunk:
    filtered_blurb = remove_invalid_unicode_chars(chunk.blurb)
    _title = chunk.source_document.get_title_for_document_index()
    filtered_title = remove_invalid_unicode_chars(_title) if _title else None
    filtered_content = remove_invalid_unicode_chars(
        generate_enriched_content_for_chunk_text(chunk)
    )
    filtered_semantic_identifier = remove_invalid_unicode_chars(
        chunk.source_document.semantic_identifier
    )
    filtered_metadata_suffix = remove_invalid_unicode_chars(
        chunk.metadata_suffix_keyword
    )
    _metadata_list = chunk.source_document.get_metadata_str_attributes()
    filtered_metadata_list = (
        [remove_invalid_unicode_chars(metadata) for metadata in _metadata_list]
        if _metadata_list
        else None
    )
    return DocumentChunk(
        document_id=chunk.source_document.id,
        chunk_index=chunk.chunk_id,
        # Use get_title_for_document_index to match the logic used when creating
        # the title_embedding in the embedder. This method falls back to
        # semantic_identifier when title is None (but not empty string).
        title=filtered_title,
        title_vector=chunk.title_embedding,
        content=filtered_content,
        content_vector=chunk.embeddings.full_embedding,
        source_type=chunk.source_document.source.value,
        metadata_list=filtered_metadata_list,
        metadata_suffix=filtered_metadata_suffix,
        last_updated=chunk.source_document.doc_updated_at,
        public=chunk.access.is_public,
        access_control_list=generate_opensearch_filtered_access_control_list(
            chunk.access
        ),
        global_boost=chunk.boost,
        semantic_identifier=filtered_semantic_identifier,
        image_file_id=chunk.image_file_id,
        # Small optimization, if this list is empty we can supply None to
        # OpenSearch and it will not store any data at all for this field, which
        # is different from supplying an empty list.
        source_links=json.dumps(chunk.source_links) if chunk.source_links else None,
        blurb=filtered_blurb,
        doc_summary=chunk.doc_summary,
        chunk_context=chunk.chunk_context,
        # Small optimization, if this list is empty we can supply None to
        # OpenSearch and it will not store any data at all for this field, which
        # is different from supplying an empty list.
        document_sets=list(chunk.document_sets) if chunk.document_sets else None,
        # Small optimization, if this list is empty we can supply None to
        # OpenSearch and it will not store any data at all for this field, which
        # is different from supplying an empty list.
        user_projects=chunk.user_project or None,
        personas=chunk.personas or None,
        primary_owners=get_experts_stores_representations(
            chunk.source_document.primary_owners
        ),
        secondary_owners=get_experts_stores_representations(
            chunk.source_document.secondary_owners
        ),
        # TODO(andrei): Consider not even getting this from
        # DocMetadataAwareIndexChunk and instead using OpenSearchDocumentIndex's
        # instance variable. One source of truth -> less chance of a very bad
        # bug in prod.
        tenant_id=TenantState(tenant_id=chunk.tenant_id, multitenant=MULTI_TENANT),
        # Store ancestor hierarchy node IDs for hierarchy-based filtering.
        ancestor_hierarchy_node_ids=chunk.ancestor_hierarchy_node_ids or None,
    )


class OpenSearchDocumentIndex(DocumentIndex):
    """OpenSearch-specific implementation of the DocumentIndex interface.

    This class provides document indexing, retrieval, and management operations
    for an OpenSearch search engine instance. It handles the complete lifecycle
    of document chunks within a specific OpenSearch index/schema.

    Each kind of embedding used should correspond to a different instance of
    this class, and therefore a different index in OpenSearch.

    If in a multitenant environment and
    VERIFY_CREATE_OPENSEARCH_INDEX_ON_INIT_MT, will verify and create the index
    if necessary on initialization. This is because there is no logic which runs
    on cluster restart which scans through all search settings over all tenants
    and creates the relevant indices.

    Args:
        tenant_state: The tenant state of the caller.
        index_name: The name of the index to interact with.
        embedding_dim: The dimensionality of the embeddings used for the index.
        embedding_precision: The precision of the embeddings used for the index.
    """

    def __init__(
        self,
        tenant_state: TenantState,
        index_name: str,
        embedding_dim: int,
        embedding_precision: EmbeddingPrecision,
    ) -> None:
        self._index_name: str = index_name
        self._tenant_state: TenantState = tenant_state
        self._client = OpenSearchIndexClient(index_name=self._index_name)

        if (
            self._tenant_state.multitenant
            and VERIFY_CREATE_OPENSEARCH_INDEX_ON_INIT_MT
            and index_name not in _verified_index_names_for_current_process
        ):
            self.verify_and_create_index_if_necessary(
                embedding_dim=embedding_dim, embedding_precision=embedding_precision
            )
            _verified_index_names_for_current_process.add(index_name)

    def verify_and_create_index_if_necessary(
        self,
        embedding_dim: int,
        embedding_precision: EmbeddingPrecision,  # noqa: ARG002
    ) -> None:
        """Verifies and creates the index if necessary.

        Also puts the desired cluster settings if not in a multitenant
        environment.

        Also puts the desired search pipeline state if not in a multitenant
        environment, creating the pipelines if they do not exist and updating
        them otherwise.

        In a multitenant environment, the above steps happen explicitly on
        setup.

        Args:
            embedding_dim: Vector dimensionality for the vector similarity part
                of the search.
            embedding_precision: Precision of the values of the vectors for the
                similarity part of the search.

        Raises:
            Exception: There was an error verifying or creating the index or
                search pipelines.
        """
        logger.debug(
            "[OpenSearchDocumentIndex] Verifying and creating index %s if necessary, with embedding dimension %s.",
            self._index_name,
            embedding_dim,
        )

        with redis_shared_lock(
            lock_name=f"{OnyxRedisLocks.OPENSEARCH_VERIFY_INDEX_LOCK_PREFIX}:{self._index_name}",
            max_time_lock_held_s=VERIFY_INDEX_LOCK_TTL_S,
            wait_for_lock_s=VERIFY_INDEX_LOCK_BLOCKING_TIMEOUT_S,
            logger=logger,
        ):
            if not self._tenant_state.multitenant:
                set_cluster_state(self._client)

            expected_mappings = DocumentSchema.get_document_schema(
                embedding_dim, self._tenant_state.multitenant
            )

            if not self._client.index_exists():
                index_settings = (
                    DocumentSchema.get_index_settings_based_on_environment()
                )
                self._client.create_index(
                    mappings=expected_mappings,
                    settings=index_settings,
                )
            else:
                # Ensure schema is up to date by applying the current mappings.
                try:
                    self._client.put_mapping(expected_mappings)
                except Exception as e:
                    logger.error(
                        "Failed to update mappings for index %s. This likely means a field type was changed which requires reindexing. Error: %s",
                        self._index_name,
                        e,
                    )
                    raise

    def index(
        self,
        chunks: Iterable[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        """Indexes an iterable of document chunks into the document index.

        Groups chunks by document ID and for each document, deletes existing
        chunks and indexes the new chunks in bulk.

        NOTE: It is assumed that chunks for a given document are not spread out
        over multiple index() calls.

        Args:
            chunks: Document chunks with all of the information needed for
                indexing to the document index.
            indexing_metadata: Information about chunk counts for efficient
                cleaning / updating.

        Raises:
            Exception: Failed to index some or all of the chunks for the
                specified documents.

        Returns:
            List of document IDs which map to unique documents as well as if the
                document is newly indexed or had already existed and was just
                updated.
        """
        total_chunks = sum(
            cc.new_chunk_cnt
            for cc in indexing_metadata.doc_id_to_chunk_cnt_diff.values()
        )
        logger.debug(
            "[OpenSearchDocumentIndex] Indexing %s chunks from %s documents for index %s.",
            total_chunks,
            len(indexing_metadata.doc_id_to_chunk_cnt_diff),
            self._index_name,
        )

        document_indexing_results: list[DocumentInsertionRecord] = []
        deleted_doc_ids: set[str] = set()
        # Buffer chunks per document as they arrive from the iterable.
        # When the document ID changes flush the buffered chunks.
        current_doc_id: str | None = None
        current_chunks: list[DocMetadataAwareIndexChunk] = []

        def _flush_chunks(doc_chunks: list[DocMetadataAwareIndexChunk]) -> None:
            assert len(doc_chunks) > 0, "doc_chunks is empty"

            # Create a batch of OpenSearch-formatted chunks for bulk insertion.
            # Since we are doing this in batches, an error occurring midway
            # can result in a state where chunks are deleted and not all the
            # new chunks have been indexed.
            chunk_batch: list[DocumentChunk] = [
                _convert_onyx_chunk_to_opensearch_document(chunk)
                for chunk in doc_chunks
            ]
            onyx_document: Document = doc_chunks[0].source_document
            # First delete the doc's chunks from the index. This is so that
            # there are no dangling chunks in the index, in the event that the
            # new document's content contains fewer chunks than the previous
            # content.
            # TODO(andrei): This can possibly be made more efficient by checking
            # if the chunk count has actually decreased. This assumes that
            # overlapping chunks are perfectly overwritten. If we can't
            # guarantee that then we need the code as-is.
            if onyx_document.id not in deleted_doc_ids:
                num_chunks_deleted = self.delete(
                    onyx_document.id, onyx_document.chunk_count
                )
                deleted_doc_ids.add(onyx_document.id)
                # If we see that chunks were deleted we assume the doc already
                # existed. We record the result before bulk_index_documents
                # runs. If indexing raises, this entire result list is discarded
                # by the caller's retry logic, so early recording is safe.
                document_indexing_results.append(
                    DocumentInsertionRecord(
                        document_id=onyx_document.id,
                        already_existed=num_chunks_deleted > 0,
                    )
                )
            # Now index. This will raise if a chunk of the same ID exists, which
            # we do not expect because we should have deleted all chunks.
            try:
                self._client.bulk_index_documents(
                    documents=chunk_batch,
                    tenant_state=self._tenant_state,
                )
            except BulkIndexError as e:
                # There are several reasons why this might be raised, but the
                # most likely one is if the deletion has not had enough time to
                # propagate throughout the index, in which case this would be
                # raised with some form of "version_conflict_engine_exception
                # version conflict, document already exists" messaging.
                # Refresh the index and try one more time. We do not refresh
                # after every delete because this may become expensive.
                logger.warning(
                    "Failed to bulk index documents: %s. Refreshing index and trying again.",
                    e,
                )
                self._client.refresh_index()
                self._client.bulk_index_documents(
                    documents=chunk_batch,
                    tenant_state=self._tenant_state,
                    # At this point we know for sure some docs from this batch
                    # may exist, so we don't want to fail in that case.
                    update_if_exists=True,
                )

        for chunk in chunks:
            doc_id = chunk.source_document.id
            if doc_id != current_doc_id:
                if current_chunks:
                    _flush_chunks(current_chunks)
                current_doc_id = doc_id
                current_chunks = [chunk]
            elif len(current_chunks) >= MAX_CHUNKS_PER_DOC_BATCH:
                _flush_chunks(current_chunks)
                current_chunks = [chunk]
            else:
                current_chunks.append(chunk)

        if current_chunks:
            _flush_chunks(current_chunks)

        return document_indexing_results

    def delete(
        self,
        document_id: str,
        chunk_count: int | None = None,  # noqa: ARG002
    ) -> int:
        """Deletes all chunks for a given document.

        Does nothing if the specified document ID does not exist.

        TODO(andrei): Consider implementing this method to delete on document
        chunk IDs vs querying for matching document chunks. Unclear if this is
        any better though.

        Args:
            document_id: The unique identifier for the document as represented
                in Onyx, not necessarily in the document index.
            chunk_count: The number of chunks in OpenSearch for the document.
                Defaults to None.

        Raises:
            Exception: Failed to delete some or all of the chunks for the
                document.

        Returns:
            The number of chunks successfully deleted.
        """
        logger.debug(
            "[OpenSearchDocumentIndex] Deleting document %s from index %s.",
            document_id,
            self._index_name,
        )
        query_body = DocumentQuery.delete_from_document_id_query(
            document_id=document_id,
            tenant_state=self._tenant_state,
        )

        return self._client.delete_by_query(query_body)

    def update(
        self,
        update_requests: list[MetadataUpdateRequest],
    ) -> None:
        """Updates some set of chunks.

        NOTE: Will raise if one of the specified document chunks do not exist.
        This may be due to a concurrent ongoing indexing operation. In that
        event callers are expected to retry after a bit once the state of the
        document index is updated.
        NOTE: Requires document chunk count be known; will raise if it is not.
        This may be caused by the same situation outlined above.
        NOTE: Will no-op if an update request has no fields to update.

        TODO(andrei): Consider exploring a batch API for OpenSearch for this
        operation.

        Args:
            update_requests: A list of update requests, each containing a list
                of document IDs and the fields to update. The field updates
                apply to all of the specified documents in each update request.

        Raises:
            Exception: Failed to update some or all of the chunks for the
                specified documents.
        """
        logger.debug(
            "[OpenSearchDocumentIndex] Processing %s chunk requests for index %s.",
            len(update_requests),
            self._index_name,
        )
        for update_request in update_requests:
            properties_to_update: dict[str, Any] = dict()
            # TODO(andrei): Nit but consider if we can use DocumentChunk here so
            # we don't have to think about passing in the appropriate types into
            # this dict.
            if update_request.access is not None:
                properties_to_update[ACCESS_CONTROL_LIST_FIELD_NAME] = (
                    generate_opensearch_filtered_access_control_list(
                        update_request.access
                    )
                )
            if update_request.document_sets is not None:
                properties_to_update[DOCUMENT_SETS_FIELD_NAME] = list(
                    update_request.document_sets
                )
            if update_request.boost is not None:
                properties_to_update[GLOBAL_BOOST_FIELD_NAME] = int(
                    update_request.boost
                )
            if update_request.hidden is not None:
                properties_to_update[HIDDEN_FIELD_NAME] = update_request.hidden
            if update_request.project_ids is not None:
                properties_to_update[USER_PROJECTS_FIELD_NAME] = list(
                    update_request.project_ids
                )
            if update_request.persona_ids is not None:
                properties_to_update[PERSONAS_FIELD_NAME] = list(
                    update_request.persona_ids
                )

            if not properties_to_update:
                if len(update_request.document_ids) > 1:
                    update_string = f"{len(update_request.document_ids)} documents"
                else:
                    update_string = f"document {update_request.document_ids[0]}"
                logger.warning(
                    "[OpenSearchDocumentIndex] Tried to update %s with no specified update fields. This will be a no-op.",
                    update_string,
                )
                continue

            doc_chunk_ids_to_update: list[str] = []
            for doc_id in update_request.document_ids:
                doc_chunk_count = update_request.doc_id_to_chunk_cnt.get(doc_id, -1)
                if doc_chunk_count < 0:
                    # This means the chunk count is not known. This is due to a
                    # race condition between doc indexing and updating steps
                    # which run concurrently when a doc is indexed. The indexing
                    # step should update chunk count shortly. This could also
                    # have been due to an older version of the indexing pipeline
                    # which did not compute chunk count, but that codepath has
                    # since been deprecated and should no longer be the case
                    # here.
                    # TODO(andrei): Fix the aforementioned race condition.
                    raise ChunkCountNotFoundError(
                        f"Tried to update document {doc_id} but its chunk count is not known. "
                        "Older versions of the application used to permit this but is not a "
                        "supported state for a document when using OpenSearch. The document was "
                        "likely just added to the indexing pipeline and the chunk count will be "
                        "updated shortly."
                    )
                if doc_chunk_count == 0:
                    raise ChunkCountZeroError(
                        f"Tried to update document {doc_id} but its chunk count was 0."
                    )

                for chunk_index in range(doc_chunk_count):
                    document_chunk_id = get_opensearch_doc_chunk_id(
                        tenant_state=self._tenant_state,
                        document_id=doc_id,
                        chunk_index=chunk_index,
                    )
                    doc_chunk_ids_to_update.append(document_chunk_id)

            self._client.bulk_update_documents(
                document_chunk_ids=doc_chunk_ids_to_update,
                properties_to_update=properties_to_update,
            )

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        filters: IndexFilters,
        # TODO(andrei): Remove this from the new interface at some point; we
        # should not be exposing this.
        batch_retrieval: bool = False,  # noqa: ARG002
        # TODO(andrei): Add a param for whether to retrieve hidden docs.
    ) -> list[InferenceChunk]:
        """
        TODO(andrei): Consider implementing this method to retrieve on document
        chunk IDs vs querying for matching document chunks.
        """
        logger.debug(
            "[OpenSearchDocumentIndex] Retrieving %s chunks for index %s.",
            len(chunk_requests),
            self._index_name,
        )
        results: list[InferenceChunk] = []
        for chunk_request in chunk_requests:
            search_hits: list[SearchHit[DocumentChunkWithoutVectors]] = []
            query_body = DocumentQuery.get_from_document_id_query(
                document_id=chunk_request.document_id,
                tenant_state=self._tenant_state,
                # NOTE: Index filters includes metadata tags which were filtered
                # for invalid unicode at indexing time. In theory it would be
                # ideal to do filtering here as well, in practice we never did
                # that in the Vespa codepath and have not seen issues in
                # production, so we deliberately conform to the existing logic
                # in order to not unknowningly introduce a possible bug.
                index_filters=filters,
                include_hidden=False,
                max_chunk_size=chunk_request.max_chunk_size,
                min_chunk_index=chunk_request.min_chunk_ind,
                max_chunk_index=chunk_request.max_chunk_ind,
            )
            search_hits = self._client.search(
                body=query_body,
                search_pipeline_id=None,
                search_type=OpenSearchSearchType.DOC_ID_RETRIEVAL,
            )
            inference_chunks_uncleaned: list[InferenceChunkUncleaned] = [
                _convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
                    search_hit.document_chunk, None, {}
                )
                for search_hit in search_hits
            ]
            inference_chunks: list[InferenceChunk] = cleanup_content_for_chunks(
                inference_chunks_uncleaned
            )
            results.extend(inference_chunks)
        return results

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        # TODO(andrei): This param is not great design, get rid of it.
        final_keywords: list[str] | None,
        query_type: QueryType,  # noqa: ARG002
        filters: IndexFilters,
        num_to_retrieve: int,
    ) -> list[InferenceChunk]:
        # TODO(andrei): There is some duplicated logic in this function with
        # others in this file.
        logger.debug(
            "[OpenSearchDocumentIndex] Hybrid retrieving %s chunks for index %s.",
            num_to_retrieve,
            self._index_name,
        )
        # TODO(andrei): This could be better, the caller should just make this
        # decision when passing in the query param. See the above comment in the
        # function signature.
        final_query = " ".join(final_keywords) if final_keywords else query
        query_body = DocumentQuery.get_hybrid_search_query(
            query_text=final_query,
            query_vector=query_embedding,
            num_hits=num_to_retrieve,
            tenant_state=self._tenant_state,
            # NOTE: Index filters includes metadata tags which were filtered
            # for invalid unicode at indexing time. In theory it would be
            # ideal to do filtering here as well, in practice we never did
            # that in the Vespa codepath and have not seen issues in
            # production, so we deliberately conform to the existing logic
            # in order to not unknowningly introduce a possible bug.
            index_filters=filters,
            include_hidden=False,
        )
        normalization_pipeline_name, _ = get_normalization_pipeline_name_and_config()
        search_hits: list[SearchHit[DocumentChunkWithoutVectors]] = self._client.search(
            body=query_body,
            search_pipeline_id=normalization_pipeline_name,
            search_type=OpenSearchSearchType.HYBRID,
        )

        # Good place for a breakpoint to inspect the search hits if you have
        # "explain" enabled.
        inference_chunks_uncleaned: list[InferenceChunkUncleaned] = [
            _convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
                search_hit.document_chunk, search_hit.score, search_hit.match_highlights
            )
            for search_hit in search_hits
        ]
        inference_chunks: list[InferenceChunk] = cleanup_content_for_chunks(
            inference_chunks_uncleaned
        )

        return inference_chunks

    def keyword_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int,
        include_hidden: bool = False,
    ) -> list[InferenceChunk]:
        # TODO(andrei): There is some duplicated logic in this function with
        # others in this file.
        logger.debug(
            "[OpenSearchDocumentIndex] Keyword retrieving %s chunks for index %s.",
            num_to_retrieve,
            self._index_name,
        )
        query_body = DocumentQuery.get_keyword_search_query(
            query_text=query,
            num_hits=num_to_retrieve,
            tenant_state=self._tenant_state,
            # NOTE: Index filters includes metadata tags which were filtered
            # for invalid unicode at indexing time. In theory it would be
            # ideal to do filtering here as well, in practice we never did
            # that in the Vespa codepath and have not seen issues in
            # production, so we deliberately conform to the existing logic
            # in order to not unknowningly introduce a possible bug.
            index_filters=filters,
            include_hidden=include_hidden,
        )
        search_hits: list[SearchHit[DocumentChunkWithoutVectors]] = self._client.search(
            body=query_body,
            search_pipeline_id=None,
            search_type=OpenSearchSearchType.KEYWORD,
        )

        inference_chunks_uncleaned: list[InferenceChunkUncleaned] = [
            _convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
                search_hit.document_chunk, search_hit.score, search_hit.match_highlights
            )
            for search_hit in search_hits
        ]
        inference_chunks: list[InferenceChunk] = cleanup_content_for_chunks(
            inference_chunks_uncleaned
        )

        return inference_chunks

    def semantic_retrieval(
        self,
        query_embedding: Embedding,
        filters: IndexFilters,
        num_to_retrieve: int,
    ) -> list[InferenceChunk]:
        # TODO(andrei): There is some duplicated logic in this function with
        # others in this file.
        logger.debug(
            "[OpenSearchDocumentIndex] Semantic retrieving %s chunks for index %s.",
            num_to_retrieve,
            self._index_name,
        )
        query_body = DocumentQuery.get_semantic_search_query(
            query_embedding=query_embedding,
            num_hits=num_to_retrieve,
            tenant_state=self._tenant_state,
            # NOTE: Index filters includes metadata tags which were filtered
            # for invalid unicode at indexing time. In theory it would be
            # ideal to do filtering here as well, in practice we never did
            # that in the Vespa codepath and have not seen issues in
            # production, so we deliberately conform to the existing logic
            # in order to not unknowningly introduce a possible bug.
            index_filters=filters,
            include_hidden=False,
        )
        search_hits: list[SearchHit[DocumentChunkWithoutVectors]] = self._client.search(
            body=query_body,
            search_pipeline_id=None,
            search_type=OpenSearchSearchType.SEMANTIC,
        )

        inference_chunks_uncleaned: list[InferenceChunkUncleaned] = [
            _convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
                search_hit.document_chunk, search_hit.score, search_hit.match_highlights
            )
            for search_hit in search_hits
        ]
        inference_chunks: list[InferenceChunk] = cleanup_content_for_chunks(
            inference_chunks_uncleaned
        )

        return inference_chunks

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
        dirty: bool | None = None,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        logger.debug(
            "[OpenSearchDocumentIndex] Randomly retrieving %s chunks for index %s.",
            num_to_retrieve,
            self._index_name,
        )
        query_body = DocumentQuery.get_random_search_query(
            tenant_state=self._tenant_state,
            index_filters=filters,
            num_to_retrieve=num_to_retrieve,
        )
        search_hits: list[SearchHit[DocumentChunkWithoutVectors]] = self._client.search(
            body=query_body,
            search_pipeline_id=None,
            search_type=OpenSearchSearchType.RANDOM,
        )
        inference_chunks_uncleaned: list[InferenceChunkUncleaned] = [
            _convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
                search_hit.document_chunk, search_hit.score, search_hit.match_highlights
            )
            for search_hit in search_hits
        ]
        inference_chunks: list[InferenceChunk] = cleanup_content_for_chunks(
            inference_chunks_uncleaned
        )

        return inference_chunks

    def index_raw_chunks(self, chunks: list[DocumentChunk]) -> None:
        """Indexes raw document chunks into OpenSearch.

        Used in the Vespa migration task. Can be deleted after migrations are
        complete.
        """
        logger.debug(
            "[OpenSearchDocumentIndex] Indexing %s raw chunks for index %s.",
            len(chunks),
            self._index_name,
        )
        # Do not raise if the document already exists, just update. This is
        # because the document may already have been indexed during the
        # OpenSearch transition period.
        self._client.bulk_index_documents(
            documents=chunks, tenant_state=self._tenant_state, update_if_exists=True
        )


class OpenSearchIndexPair(DocumentIndex):
    """Pair wrapper that fans operations out to a primary OpenSearch index and
    an optional secondary one.

    Mirrors the previous ``OpenSearchOldDocumentIndex`` semantics minus the
    OLD-interface translation:
      - `index` writes only to primary (a separate pipeline backfills
        secondary).
      - `delete`, `update`, `verify_and_create_index_if_necessary` fan out to
        both.
      - All retrieval goes to primary.
    """

    def __init__(
        self,
        primary: OpenSearchDocumentIndex,
        secondary: OpenSearchDocumentIndex | None,
        # Embedding info needed at verify-and-create time per index.
        # TODO(andrei): This is dumb, fix this.
        secondary_embedding_dim: int | None = None,
        secondary_embedding_precision: EmbeddingPrecision | None = None,
    ) -> None:
        # All three secondary fields must be set together or all None — checked
        # independently so a partially-set state surfaces here rather than
        # deferring to a less informative assertion in verify_and_create.
        secondary_set = secondary is not None
        dim_set = secondary_embedding_dim is not None
        precision_set = secondary_embedding_precision is not None
        if not (secondary_set == dim_set == precision_set):
            raise ValueError(
                "Bug: Secondary OpenSearchDocumentIndex, secondary_embedding_dim, and "
                "secondary_embedding_precision must all be set together or all be None. Got: "
                f"secondary={secondary_set}, embedding_dim={dim_set}, "
                f"embedding_precision={precision_set}."
            )
        self._primary = primary
        self._secondary = secondary
        self._secondary_embedding_dim = secondary_embedding_dim
        self._secondary_embedding_precision = secondary_embedding_precision

    def verify_and_create_index_if_necessary(
        self,
        embedding_dim: int,
        embedding_precision: EmbeddingPrecision,
    ) -> None:
        self._primary.verify_and_create_index_if_necessary(
            embedding_dim, embedding_precision
        )
        if self._secondary is not None:
            assert self._secondary_embedding_dim is not None, (
                "Bug: Secondary embedding dimension is not set."
            )
            assert self._secondary_embedding_precision is not None, (
                "Bug: Secondary embedding precision is not set."
            )
            self._secondary.verify_and_create_index_if_necessary(
                self._secondary_embedding_dim, self._secondary_embedding_precision
            )

    def index(
        self,
        chunks: Iterable[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        return self._primary.index(chunks, indexing_metadata)

    def delete(self, document_id: str, chunk_count: int | None = None) -> int:
        total = self._primary.delete(document_id, chunk_count)
        if self._secondary is not None:
            total += self._secondary.delete(document_id, chunk_count)
        return total

    def update(self, update_requests: list[MetadataUpdateRequest]) -> None:
        self._primary.update(update_requests)
        if self._secondary is not None:
            self._secondary.update(update_requests)

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        return self._primary.id_based_retrieval(
            chunk_requests, filters, batch_retrieval
        )

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        query_type: QueryType,
        filters: IndexFilters,
        num_to_retrieve: int,
    ) -> list[InferenceChunk]:
        return self._primary.hybrid_retrieval(
            query,
            query_embedding,
            final_keywords,
            query_type,
            filters,
            num_to_retrieve,
        )

    def keyword_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int,
        include_hidden: bool = False,
    ) -> list[InferenceChunk]:
        return self._primary.keyword_retrieval(
            query, filters, num_to_retrieve, include_hidden=include_hidden
        )

    def semantic_retrieval(
        self,
        query_embedding: Embedding,
        filters: IndexFilters,
        num_to_retrieve: int,
    ) -> list[InferenceChunk]:
        return self._primary.semantic_retrieval(
            query_embedding, filters, num_to_retrieve
        )

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
        dirty: bool | None = None,
    ) -> list[InferenceChunk]:
        return self._primary.random_retrieval(filters, num_to_retrieve, dirty)

    @property
    def primary(self) -> OpenSearchDocumentIndex:
        return self._primary

    @property
    def secondary(self) -> OpenSearchDocumentIndex | None:
        return self._secondary
