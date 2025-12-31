import httpx

from onyx.configs.chat_configs import TITLE_CONTENT_RATIO
from onyx.context.search.enums import QueryType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceChunkUncleaned
from onyx.context.search.models import QueryExpansionType
from onyx.db.enums import EmbeddingPrecision
from onyx.db.models import DocumentSource
from onyx.document_index.interfaces import DocumentIndex as OldDocumentIndex
from onyx.document_index.interfaces import (
    DocumentInsertionRecord as OldDocumentInsertionRecord,
)
from onyx.document_index.interfaces import IndexBatchParams
from onyx.document_index.interfaces import UpdateRequest
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
from onyx.document_index.opensearch.client import OpenSearchIndexingResult
from onyx.document_index.opensearch.schema import DocumentChunk
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import Document
from onyx.utils.logger import setup_logger
from shared_configs.model_server_models import Embedding

logger = setup_logger(__name__)


def _convert_opensearch_chunk_to_inference_chunk_uncleaned(
    chunk: DocumentChunk,
) -> InferenceChunkUncleaned:
    # we will have niche feature regressions
    return InferenceChunkUncleaned(
        chunk_id=chunk.chunk_index,
        # blurb TODO(andrei) required
        # top of doc, we use it in the ui, so needed for now but we should show match highlights
        blurb="",
        content=chunk.content,
        # source_links TODO(andrei): This one is weird, the typing is
        # source_links: dict[int, str] | None, comment is: Holds the link and
        # the offsets into the raw Chunk text.
        # files are the only connector that is weird
        source_links=None,
        image_file_id=chunk.image_file_name,
        # section_continuation TODO(andrei) required
        # dont think we need that anymore. if section needed to be split into diff chunks. every connector gives back sections.
        # what is a section? click on citation, brings to right place in doc
        # each chunk has its own link?
        section_continuation=False,
        document_id=chunk.document_id,
        source_type=DocumentSource(chunk.source_type),
        # semantic_identifier TODO(andrei) required
        # should never be none
        semantic_identifier=(
            chunk.semantic_identifier if chunk.semantic_identifier else ""
        ),
        title=chunk.title,
        # TODO(andrei): This doesn't work for the same reason as the boost
        # comment in the next function.
        # none title should be reweighted to 0?
        # boost=int(chunk.global_boost),
        # we can remove this
        # yuhong things os has some thing oob for this
        boost=1,
        # recency_bias TODO(andrei) required
        recency_bias=1.0,
        # score TODO(andrei)
        # this is how good the match is, we need this, key insight is we can order chunks by this
        score=None,
        hidden=chunk.hidden,
        # dont worry abt these for now
        # is_relevant TODO(andrei)
        # relevance_explanation TODO(andrei)
        # metadata TODO(andrei)
        # arb key value, these get appended to content, need to unappend
        # instead do string slice on indices where we appended content
        metadata={},
        # match_highlights TODO(andrei)
        # useful. vector db needs to supply this, dont wanna do string match ourselves
        match_highlights=[],
        # doc_summary TODO(andrei) required
        # summary of entire doc, specifically if you enable contextual retrieval enabled
        doc_summary="",
        # chunk_context TODO(andrei) required
        # same thing as contx ret, llm gens context for each chunk
        chunk_context="",
        updated_at=chunk.last_updated,
        # author of doc? if its null keeps being null
        # primary_owners TODO(andrei)
        # secondary_owners TODO(andrei)
        # large_chunk_reference_ids TODO(andrei) dont worry
        # is_federated TODO(andrei) required
        is_federated=False,
        # metadata_suffix TODO(andrei)
        # this is the natural language thing we were talking abt
        metadata_suffix=None,
    )


def _convert_onyx_chunk_to_opensearch_document(
    chunk: DocMetadataAwareIndexChunk,
) -> DocumentChunk:
    return DocumentChunk(
        # very often link to the source. tenant.
        # for uniqueness stuff rely on tne vector dbs id
        document_id=chunk.source_document.id,
        chunk_index=chunk.chunk_id,
        title=chunk.source_document.title,
        title_vector=chunk.title_embedding,
        content=chunk.content,
        content_vector=chunk.embeddings.full_embedding,
        # TODO(andrei): Hmm.
        # we should know this. reason to have this is convenience, but it could
        # also change when you change your embedding model, maybe can remove it,
        # yuhong to look at this
        num_tokens=-1,
        source_type=chunk.source_document.source.value,
        # TODO(andrei): Hmm.
        # metadata=chunk.source_document.metadata,
        last_updated=chunk.source_document.doc_updated_at,
        # TODO(andrei): Hmm.
        # created_at=None, this is fine? like websites yuhong check
        public=chunk.access.is_public,
        # TODO(andrei): Hmm.
        # access_control_list=chunk.access.to_acl(),
        # TODO(andrei): Hmm.
        hidden=False,
        # TODO(andrei): This doesn't work bc global_boost is float, presumably
        # between 0.0 and inf (check this) and chunk.boost is an int from -inf
        # to +inf.
        # global_boost=chunk.boost,
        semantic_identifier=chunk.source_document.semantic_identifier,
        # TODO(andrei)
        # ask chris
        # image_file_name=None,
        # TODO(andrei): Hmm.
        # should not be none?
        # source_links=chunk.source_document.source_links,
        document_sets=list(chunk.document_sets) if chunk.document_sets else None,
        project_ids=list(chunk.user_project) if chunk.user_project else None,
        tenant_id=chunk.tenant_id,
    )


class OpenSearchOldDocumentIndex(OldDocumentIndex):
    """
    Wrapper for OpenSearch to adapt the new DocumentIndex interface with
    invocations to the old DocumentIndex interface in the hotpath.

    The analogous class for Vespa is VespaIndex which calls to
    VespaDocumentIndex.

    TODO(andrei): This is purely temporary until there are no more references to
    the old interface in hotpath.
    """

    def __init__(
        self,
        index_name: str,
        secondary_index_name: str | None,
        large_chunks_enabled: bool,
        secondary_large_chunks_enabled: bool | None,
        multitenant: bool = False,
        httpx_client: httpx.Client | None = None,
    ) -> None:
        # Initialize parent with index names
        super().__init__(
            index_name=index_name,
            secondary_index_name=secondary_index_name,
        )
        self._real_index = OpenSearchDocumentIndex(
            index_name=index_name,
            # TODO(andrei): Sus.
            tenant_state=TenantState(tenant_id="", multitenant=multitenant),
        )

    @staticmethod
    def register_multitenant_indices(
        indices: list[str],
        embedding_dims: list[int],
        embedding_precisions: list[EmbeddingPrecision],
    ) -> None:
        raise NotImplementedError(
            "[ANDREI]: Multitenant index registration is not implemented for OpenSearch."
        )

    def ensure_indices_exist(
        self,
        primary_embedding_dim: int,
        primary_embedding_precision: EmbeddingPrecision,
        secondary_index_embedding_dim: int | None,
        secondary_index_embedding_precision: EmbeddingPrecision | None,
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
            old_count = index_batch_params.doc_id_to_previous_chunk_cnt.get(doc_id, 0)
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
        tenant_id: str,
        chunk_count: int | None,
    ) -> int:
        return self._real_index.delete(doc_id, chunk_count)

    def update_single(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        chunk_count: int | None,
        fields: VespaDocumentFields | None,
        user_fields: VespaDocumentUserFields | None,
    ) -> None:
        if fields is None and user_fields is None:
            raise ValueError(
                f"Bug: Tried to update document {doc_id} with no updated fields or user fields."
            )

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

        return self._real_index.update([update_request], old_doc_id_to_new_doc_id={})

    def update(
        self,
        update_requests: list[UpdateRequest],
        *,
        tenant_id: str,
    ) -> None:
        raise NotImplementedError("[ANDREI]: Update is not implemented for OpenSearch.")

    def id_based_retrieval(
        self,
        chunk_requests: list[VespaChunkRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
        get_large_chunks: bool = False,
    ) -> list[InferenceChunk]:
        # Convert VespaChunkRequest to DocumentSectionRequest.
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
        time_decay_multiplier: float,
        num_to_retrieve: int,
        ranking_profile_type: QueryExpansionType = QueryExpansionType.SEMANTIC,
        offset: int = 0,
        title_content_ratio: float | None = TITLE_CONTENT_RATIO,
    ) -> list[InferenceChunk]:
        # The new interface doesn't use hybrid_alpha, time_decay_multiplier,
        # ranking_profile_type, or title_content_ratio - they're handled
        # internally by OpenSearch's normalization pipeline.

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
            offset=offset,
        )

    def admin_retrieval(
        self,
        query: str,
        filters: IndexFilters,
        num_to_retrieve: int,
        offset: int = 0,
    ) -> list[InferenceChunk]:
        raise NotImplementedError(
            "[ANDREI]: Admin retrieval is not implemented for OpenSearch."
        )

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 100,
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
    """

    def __init__(
        self,
        index_name: str,
        tenant_state: TenantState,
    ) -> None:
        self._index_name = index_name
        self._tenant_id = tenant_state.tenant_id
        self._multitenant = tenant_state.multitenant
        if self._multitenant:
            assert (
                self._tenant_id
            ), "Bug: Must supply a tenant id if in multitenant mode."
        self._os_client = OpenSearchClient(index_name=self._index_name)

    def verify_and_create_index_if_necessary(
        self, embedding_dim: int, embedding_precision: EmbeddingPrecision
    ) -> None:
        raise NotImplementedError(
            "[ANDREI]: verify_and_create_index_if_necessary is not implemented for OpenSearch."
        )

    def index(
        self,
        chunks: list[DocMetadataAwareIndexChunk],
        indexing_metadata: IndexingMetadata,
    ) -> list[DocumentInsertionRecord]:
        # Set of doc IDs.
        unique_docs_to_be_indexed: set[str] = set()
        results: list[DocumentInsertionRecord] = []
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
            indexing_result = self._os_client.index_document(opensearch_document_chunk)
            if indexing_result != OpenSearchIndexingResult.CREATED:
                # No other result makes sense in this context; something went
                # wrong.
                raise RuntimeError(
                    f"Failed to index document ID {onyx_document.id}, chunk ID {chunk.chunk_id}: "
                    f"got indexing result {indexing_result} instead of created."
                )

            if document_insertion_record is not None:
                # Only add records once per doc. This object is not None only if
                # we've seen this doc for the first time in this for loop.
                results.append(document_insertion_record)

        return results

    def delete(self, document_id: str, chunk_count: int | None = None) -> int:
        if not chunk_count:
            logger.warning(
                f"The chunk count for document with ID {document_id} is not set. "
                "This is unexpected, but deletion can still proceed, albeit possibly less efficiently."
            )
        # TODO(andrei): This needs to be implemented.
        self._os_client.delete_document()
        return -1

    def update(
        self,
        update_requests: list[MetadataUpdateRequest],
        # TODO(andrei), WARNING: Very temporary, this is not the interface we want
        # in Updatable, we only have this to continue supporting
        # user_file_docid_migration_task for Vespa which should be done soon.
        old_doc_id_to_new_doc_id: dict[str, str],
    ) -> None:
        logger.info("[ANDREI]: Updating documents...")
        # TODO(andrei): This needs to be implemented.

    def id_based_retrieval(
        self,
        chunk_requests: list[DocumentSectionRequest],
        filters: IndexFilters,
        batch_retrieval: bool = False,
    ) -> list[InferenceChunk]:
        logger.info(
            f"[ANDREI]: Retrieving chunks for {len(chunk_requests)} documents..."
        )
        results: list[InferenceChunk] = []
        return results
        # TODO(andrei): This needs to be implemented.

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
        # TODO(andrei): This needs to be implemented.
        results: list[InferenceChunk] = []
        return results

    def random_retrieval(
        self,
        filters: IndexFilters,
        num_to_retrieve: int = 100,
        dirty: bool | None = None,
    ) -> list[InferenceChunk]:
        raise NotImplementedError(
            "[ANDREI]: Random retrieval is not implemented for OpenSearch."
        )
