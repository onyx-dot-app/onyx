import json
from typing import Any

import httpx
from opensearchpy import NotFoundError

from onyx.access.models import DocumentAccess
from onyx.configs.app_configs import USING_AWS_MANAGED_OPENSEARCH
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_experts_stores_representations,
)
from onyx.connectors.models import convert_metadata_list_of_strings_to_dict
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.db.models import DocumentSource
from onyx.document_index.chunk_content_enrichment import cleanup_content_for_chunks
from onyx.document_index.chunk_content_enrichment import (
    generate_enriched_content_for_chunk_text,
)
from onyx.document_index.interfaces import DocumentIndex as OldDocumentIndex
from onyx.document_index.interfaces import (
    DocumentInsertionRecord as OldDocumentInsertionRecord,
)
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.interfaces_new import DocumentInsertionRecord
from onyx.document_index.interfaces_new import DocumentSectionRequest
from onyx.document_index.interfaces_new import IndexingMetadata
from onyx.document_index.interfaces_new import MetadataUpdateRequest
from onyx.document_index.interfaces_new import TenantState
from onyx.document_index.opensearch.client import OpenSearchClient
from onyx.document_index.opensearch.client import SearchHit
from onyx.document_index.opensearch.schema import ACCESS_CONTROL_LIST_FIELD_NAME
from onyx.document_index.opensearch.schema import CONTENT_FIELD_NAME
from onyx.document_index.opensearch.schema import DOCUMENT_SETS_FIELD_NAME
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.document_index.opensearch.schema import DocumentSchema
from onyx.document_index.opensearch.schema import get_opensearch_doc_chunk_id
from onyx.document_index.opensearch.schema import GLOBAL_BOOST_FIELD_NAME
from onyx.document_index.opensearch.schema import HIDDEN_FIELD_NAME
from onyx.document_index.opensearch.schema import USER_PROJECTS_FIELD_NAME
from onyx.document_index.opensearch.search import DocumentQuery
from onyx.document_index.opensearch.search import (
    MIN_MAX_NORMALIZATION_PIPELINE_CONFIG,
)
from onyx.document_index.opensearch.search import (
    MIN_MAX_NORMALIZATION_PIPELINE_NAME,
)
from onyx.document_index.opensearch.search import (
    ZSCORE_NORMALIZATION_PIPELINE_CONFIG,
)
from onyx.document_index.opensearch.search import (
    ZSCORE_NORMALIZATION_PIPELINE_NAME,
)
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import Document
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import remove_invalid_unicode_chars
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id
from shared_configs.model_server_models import Embedding


logger = setup_logger(__name__)


class ChunkCountNotFoundError(ValueError):
    """Raised when a document has no chunk count."""


def generate_opensearch_filtered_access_control_list(
    access: DocumentAccess,
) -> list[str]:
    """Generates an access control list with PUBLIC_DOC_PAT removed.

    In the OpenSearch schema this is represented by PUBLIC_FIELD_NAME.
    """
    access_control_list = access.to_acl()
    access_control_list.discard(PUBLIC_DOC_PAT)
    return list(access_control_list)


def _convert_retrieved_opensearch_chunk_to_inference_chunk_uncleaned(
    chunk: DocumentChunk,
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


class OpenSearchOldDocumentIndex(OldDocumentIndex):
    """
    Wrapper for OpenSearch to adapt the new DocumentIndex interface with
    invocations to the old DocumentIndex interface in the hotpath.

    The analogous class for Vespa is VespaIndex which calls to
    VespaDocumentIndex.

    TODO(andrei): This is very dumb and purely temporary until there are no more
    references to the old interface in the hotpath.
    """

    def __init__(
        self,
        index_name: str,
        secondary_index_name: str | None,
        large_chunks_enabled: bool,  # noqa: ARG002
        secondary_large_chunks_enabled: bool | None,  # noqa: ARG002
        multitenant: bool = False,
        httpx_client: httpx.Client | None = None,  # noqa: ARG002
    ) -> None:
        super().__init__(
            index_name=index_name,
            secondary_index_name=secondary_index_name,
        )
        if multitenant:
            raise ValueError(
                "Bug: OpenSearch is not yet ready for multitenant environments but something tried to use it."
            )
        if multitenant != MULTI_TENANT:
            raise ValueError(
                "Bug: Multitenant mismatch when initializing an OpenSearchDocumentIndex. "
                f"Expected {MULTI_TENANT}, got {multitenant}."
            )
        tenant_id = get_current_tenant_id()
        self._real_index = OpenSearchDocumentIndex(
            index_name=index_name,
            tenant_state=TenantState(tenant_id=tenant_id, multitenant=multitenant),
        )

    @staticmethod
    def register_multitenant_indices(
        indices: list[str],
        embedding_dims: list[int],
        embedding_precisions: list[EmbeddingPrecision],
    ) -> None:
        # TODO(andrei): Implement.
        raise NotImplementedError(
            "Multitenant index registration is not yet implemented for OpenSearch."
        )

    def ensure_indices_exist(
        self,
        primary_embedding_dim: int,
        primary_embedding_precision: EmbeddingPrecision,
        secondary_index_embedding_dim: int | None,  # noqa: ARG002
        secondary_index_embedding_precision: EmbeddingPrecision | None,  # noqa: ARG002
    ) -> None:
        # Only handle primary index for now, ignore secondary.
        return self._real_index.verify_and_create_index_if_necessary(
            primary_embedding_dim, primary_embedding_precision
        )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        index_batch_params: IndexBatchParams,
    ) -> set[OldDocumentInsertionRecord]:
        # Convert IndexBatchParams to IndexingMetadata.
        chunk_counts: dict[str, IndexingMetadata.ChunkCounts] = {}
        for doc_id in index_batch_params.doc_id_to_new_chunk_cnt:
            old_count = index_batch_params.doc_id_to_previous_chunk_cnt[doc_id]
            new_count = index_batch_params.doc_id_to_new_chunk_cnt[doc_id]
            chunk_counts[doc_id] = IndexingMetadata.ChunkCounts(
                old_chunk_cnt=old_count,
                new_chunk_cnt=new_count,
            )

        indexing_metadata = IndexingMetadata(doc_id_to_chunk_cnt_diff=chunk_counts)

        results = self._real_index.index(chunks, indexing_metadata)

        # Convert list[DocumentInsertionRecord] to
        # set[OldDocumentInsertionRecord].
        return {
            OldDocumentInsertionRecord(
                document_id=record.document_id,
                already_existed=record.already_existed,
            )
            for record in results
        }

    def delete_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,  # noqa: ARG002
        chunk_count: int | None,
    ) -> int:
        return self._real_index.delete(doc_id, chunk_count)

    def update_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,  # noqa: ARG002
        chunk_count: int | None,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> None:
        if fields is None and user_fields is None:
            logger.warning(
                f"Tried to update document {doc_id} with no updated fields or user fields."
            )
            return

        # Convert VespaDocumentFields to MetadataUpdateRequest.
        update_request = MetadataUpdateRequest(
            document_ids=[doc_id],
            doc_id_to_chunk_cnt={
                doc_id: chunk_count if chunk_count is not None else -1
            },
            access=fields.access if fields else None,
            document_sets=fields.document_sets if fields else None,
            boost=fields.boost if fields else None,
            hidden=fields.hidden if fields else None,
            project_ids=(
                set(user_fields.user_projects)
                if user_fields and user_fields.user_projects
                else None
            ),
        )

        try:
            self._real_index.update([update_request])
        except NotFoundError:
            logger.exception(
                f"Tried to update document {doc_id} but at least one of its chunks was not found in OpenSearch. "
                "This is likely due to it not having been indexed yet. Skipping update for now..."
            )
            return
        except ChunkCountNotFoundError:
            logger.exception(
                f"Tried to update document {doc_id} but its chunk count is not known. We tolerate this for now "
                "but this will not be an acceptable state once OpenSearch is the primary document index and the "
                "indexing/updating race condition is fixed."
            )
            return

    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
        get_large_chunks: bool = False,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        section_requests = [
            DocumentSectionRequest(
                document_id=req.document_id,
                min_chunk_ind=req.min_chunk_ind,
                max_chunk_ind=req.max_chunk_ind,
            )
            for req in chunk_requests
        ]

        return self._real_index.id_based_retrieval(
            section_requests, filters, batch_retrieval
        )

    def hybrid_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        final_keywords: list[str] | None,
        filters: IndexFilters,
        hybrid_alpha: float,
        time_decay_multiplier: float,  # noqa: ARG002
        num_to_retrieve: int,
        ranking_profile_type: QueryExpansionType = QueryExpansionType.SEMANTIC,  # noqa: ARG002
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,  # noqa: ARG002
    ) -> list[InferenceChunk]:
        # Determine query type based on hybrid_alpha.
        if hybrid_alpha >= 0.8:
            query_type = QueryType.SEMANTIC
        elif hybrid_alpha <= 0.2:
            query_type = QueryType.KEYWORD
        else:
            query_type = QueryType.SEMANTIC  # Default to semantic for hybrid.

        return self._real_index.hybrid_retrieval(
            query=query,
            query_embedding=query_embedding,
            final_keywords=final_keywords,
            query_type=query_type,
            filters=filters,
            num_to_retrieve=num_to_retrieve,
        )

    def admin_retrieval(
        self,
        query: str,
        query_embedding: Embedding,
        filters: IndexFilters,
        num_to_retrieve: int = NUM_RETURNED_HITS,
    ) -> list[InferenceChunk]:
        return self._real_index.hybrid_retrieval(
            query=query,
            query_embedding=query_embedding,
            final_keywords=None,
            query_type=QueryType.KEYWORD,
            filters=filters,
            num_to_retrieve=num_to_retrieve,
        )

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 10,
    ) -> list[InferenceChunk]:
        return self._real_index.random_retrieval(
            filters=filters,
            num_to_retrieve=num_to_retrieve,
            dirty=None,
        )


class OpenSearchDocumentIndex(DocumentIndex):
    """OpenSearch-specific implementation of the DocumentIndex interface.

    This class provides document indexing, retrieval, and management operations
    for an OpenSearch search engine instance. It handles the complete lifecycle
    of document chunks within a specific OpenSearch index/schema.

    Although not yet used in this way in the codebase, each kind of embedding
    used should correspond to a different instance of this class, and therefore
    a different index in OpenSearch.
    """

    def __init__(
        self,
        index_name: str,
        tenant_state: TenantState,
    ) -> None:
        self._index_name: str = index_name
        self._tenant_state: TenantState = tenant_state
        self._os_client = OpenSearchClient(index_name=self._index_name)

    def verify_and_create_index_if_necessary(
        self,
        embedding_dim: int,
        embedding_precision: EmbeddingPrecision,  # noqa: ARG002
    ) -> None:
        """Verifies and creates the index if necessary.

        Also puts the desired search pipeline state, creating the pipelines if
        they do not exist and updating them otherwise.

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
            f"[OpenSearchDocumentIndex] Verifying and creating index {self._index_name} if necessary, "
            f"with embedding dimension {embedding_dim}."
        )
        expected_mappings = DocumentSchema.get_document_schema(
            embedding_dim, self._tenant_state.multitenant
        )
        if not self._os_client.index_exists():
            if not self._os_client.set_cluster_auto_create_index_setting(enabled=False):
                logger.error(
                    f"Failed to disable the auto create index setting for index {self._index_name}. "
                    "This may cause unexpected index creation when indexing documents into an index that does not exist. "
                    "Not taking any further action..."
                )
            if USING_AWS_MANAGED_OPENSEARCH:
                index_settings = (
                    DocumentSchema.get_index_settings_for_aws_managed_opensearch()
                )
            else:
                index_settings = DocumentSchema.get_index_settings()
            self._os_client.create_index(
                mappings=expected_mappings,
                settings=index_settings,
            )
        if not self._os_client.validate_index(
            expected_mappings=expected_mappings,
        ):
            raise RuntimeError(
                f"The index {self._index_name} is not valid. The expected mappings do not match the actual mappings."
            )

        self._os_client.create_search_pipeline(
            pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME,
            pipeline_body=MIN_MAX_NORMALIZATION_PIPELINE_CONFIG,
        )
        self._os_client.create_search_pipeline(
            pipeline_id=ZSCORE_NORMALIZATION_PIPELINE_NAME,
            pipeline_body=ZSCORE_NORMALIZATION_PIPELINE_CONFIG,
        )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,  # noqa: ARG002
    ) -> list[DocumentInsertionRecord]:
        logger.debug(
            f"[OpenSearchDocumentIndex] Indexing {len(chunks)} chunks for index {self._index_name}."
        )
        # Set of doc IDs.
        unique_docs_to_be_indexed: set[str] = set()
        document_indexing_results: list[DocumentInsertionRecord] = []
        for chunk in chunks:
            document_insertion_record: DocumentInsertionRecord | None = None
            onyx_document: Document = chunk.source_document
            if onyx_document.id not in unique_docs_to_be_indexed:
                # If this is the first time we see this doc in this indexing
                # operation, first delete the doc's chunks from the index. This
                # is so that there are no dangling chunks in the index, in the
                # event that the new document's content contains fewer chunks
                # than the previous content.
                # TODO(andrei): This can possibly be made more efficient by
                # checking if the chunk count has actually decreased. This
                # assumes that overlapping chunks are perfectly overwritten. If
                # we can't guarantee that then we need the code as-is.
                unique_docs_to_be_indexed.add(onyx_document.id)
                num_chunks_deleted = self.delete(
                    onyx_document.id, onyx_document.chunk_count
                )
                # If we see that chunks were deleted we assume the doc already
                # existed.
                document_insertion_record = DocumentInsertionRecord(
                    document_id=onyx_document.id,
                    already_existed=num_chunks_deleted > 0,
                )

            opensearch_document_chunk = _convert_onyx_chunk_to_opensearch_document(
                chunk
            )
            # TODO(andrei): After our client supports batch indexing, use that
            # here.
            self._os_client.index_document(
                document=opensearch_document_chunk, tenant_state=self._tenant_state
            )

            if document_insertion_record is not None:
                # Only add records once per doc. This object is not None only if
                # we've seen this doc for the first time in this for-loop.
                document_indexing_results.append(document_insertion_record)

        return document_indexing_results

    def delete(
        self, document_id: str, chunk_count: int | None = None  # noqa: ARG002
    ) -> int:
        """Deletes all chunks for a given document.

        Does nothing if the specified document ID does not exist.

        TODO(andrei): Consider implementing this method to delete on document
        chunk IDs vs querying for matching document chunks.

        Args:
            document_id: The ID of the document to delete.
            chunk_count: The number of chunks in OpenSearch for the document.
                Defaults to None.

        Raises:
            Exception: Failed to delete some or all of the chunks for the
                document.

        Returns:
            The number of chunks successfully deleted.
        """
        logger.debug(
            f"[OpenSearchDocumentIndex] Deleting document {document_id} from index {self._index_name}."
        )
        query_body = DocumentQuery.delete_from_document_id_query(
            document_id=document_id,
            tenant_state=self._tenant_state,
        )

        return self._os_client.delete_by_query(query_body)

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
            f"[OpenSearchDocumentIndex] Updating {len(update_requests)} chunks for index {self._index_name}."
        )
        for update_request in update_requests:
            properties_to_update: dict[str, Any] = dict()
            # TODO(andrei): Nit but consider if we can use DocumentChunk
            # here so we don't have to think about passing in the
            # appropriate types into this dict.
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

            if not properties_to_update:
                if len(update_request.document_ids) > 1:
                    update_string = f"{len(update_request.document_ids)} documents"
                else:
                    update_string = f"document {update_request.document_ids[0]}"
                logger.warning(
                    f"[OpenSearchDocumentIndex] Tried to update {update_string} "
                    "with no specified update fields. This will be a no-op."
                )
                continue

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
                        f"Tried to update document {doc_id} but its chunk count is not known. Older versions of the "
                        "application used to permit this but is not a supported state for a document when using OpenSearch. "
                        "The document was likely just added to the indexing pipeline and the chunk count will be updated shortly."
                    )
                if doc_chunk_count == 0:
                    raise ValueError(
                        f"Bug: Tried to update document {doc_id} but its chunk count was 0."
                    )

                for chunk_index in range(doc_chunk_count):
                    document_chunk_id = get_opensearch_doc_chunk_id(
                        tenant_state=self._tenant_state,
                        document_id=doc_id,
                        chunk_index=chunk_index,
                    )
                    self._os_client.update_document(
                        document_chunk_id=document_chunk_id,
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
            f"[OpenSearchDocumentIndex] Retrieving {len(chunk_requests)} chunks for index {self._index_name}."
        )
        results: list[InferenceChunk] = []
        for chunk_request in chunk_requests:
            search_hits: list[SearchHit[DocumentChunk]] = []
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
            search_hits = self._os_client.search(
                body=query_body,
                search_pipeline_id=None,
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
        logger.debug(
            f"[OpenSearchDocumentIndex] Hybrid retrieving {num_to_retrieve} chunks for index {self._index_name}."
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
        search_hits: list[SearchHit[DocumentChunk]] = self._os_client.search(
            body=query_body,
            search_pipeline_id=MIN_MAX_NORMALIZATION_PIPELINE_NAME,
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
            f"[OpenSearchDocumentIndex] Randomly retrieving {num_to_retrieve} chunks for index {self._index_name}."
        )
        query_body = DocumentQuery.get_random_search_query(
            tenant_state=self._tenant_state,
            index_filters=filters,
            num_to_retrieve=num_to_retrieve,
        )
        search_hits: list[SearchHit[DocumentChunk]] = self._os_client.search(
            body=query_body,
            search_pipeline_id=None,
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
            f"[OpenSearchDocumentIndex] Indexing {len(chunks)} raw chunks for index {self._index_name}."
        )
        # Do not raise if the document already exists, just update. This is
        # because the document may already have been indexed during the
        # OpenSearch transition period.
        self._os_client.bulk_index_documents(
            documents=chunks, tenant_state=self._tenant_state, update_if_exists=True
        )
