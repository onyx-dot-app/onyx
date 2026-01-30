import contextlib
from collections.abc import Generator

from sqlalchemy.engine.util import TransactionalContext
from sqlalchemy.orm import Session

from onyx.access.access import get_access_for_documents
from onyx.access.models import DocumentAccess
from onyx.configs.constants import DEFAULT_BOOST
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.chunk import update_chunk_boost_components__no_commit
from onyx.db.document import fetch_chunk_counts_for_documents
from onyx.db.document import mark_document_as_indexed_for_cc_pair__no_commit
from onyx.db.document import prepare_to_modify_documents
from onyx.db.document import update_docs_chunk_count__no_commit
from onyx.db.document import update_docs_last_modified__no_commit
from onyx.db.document import update_docs_updated_at__no_commit
from onyx.db.document_set import fetch_document_sets_for_documents
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from onyx.indexing.models import BuildMetadataAwareChunksResult
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk
from onyx.indexing.models import UpdatableChunkData
from onyx.redis.redis_hierarchy import get_ancestors_from_raw_id
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


class DocumentIndexingBatchAdapter:
    """Default adapter: handles DB prep, locking, metadata enrichment, and finalize.

    Keeps orchestration logic in the pipeline and side-effects in the adapter.
    """

    def __init__(
        self,
        db_session: Session,
        connector_id: int,
        credential_id: int,
        tenant_id: str,
        index_attempt_metadata: IndexAttemptMetadata,
    ):
        self.db_session = db_session
        self.connector_id = connector_id
        self.credential_id = credential_id
        self.tenant_id = tenant_id
        self.index_attempt_metadata = index_attempt_metadata

    def prepare(
        self, documents: list[Document], ignore_time_skip: bool
    ) -> DocumentBatchPrepareContext | None:
        """Upsert docs, map CC pairs, return context or mark as indexed if no-op."""
        context = index_doc_batch_prepare(
            documents=documents,
            index_attempt_metadata=self.index_attempt_metadata,
            db_session=self.db_session,
            ignore_time_skip=ignore_time_skip,
        )

        if not context:
            # even though we didn't actually index anything, we should still
            # mark them as "completed" for the CC Pair in order to make the
            # counts match
            mark_document_as_indexed_for_cc_pair__no_commit(
                connector_id=self.index_attempt_metadata.connector_id,
                credential_id=self.index_attempt_metadata.credential_id,
                document_ids=[doc.id for doc in documents],
                db_session=self.db_session,
            )
            self.db_session.commit()

        return context

    @contextlib.contextmanager
    def lock_context(
        self, documents: list[Document]
    ) -> Generator[TransactionalContext, None, None]:
        """Acquire transaction/row locks on docs for the critical section."""
        with prepare_to_modify_documents(
            db_session=self.db_session, document_ids=[doc.id for doc in documents]
        ) as transaction:
            yield transaction

    def build_metadata_aware_chunks(
        self,
        chunks_with_embeddings: list[IndexChunk],
        chunk_content_scores: list[float],
        tenant_id: str,
        context: DocumentBatchPrepareContext,
    ) -> BuildMetadataAwareChunksResult:
        """Enrich chunks with access, document sets, boosts, token counts, and hierarchy."""

        no_access = DocumentAccess.build(
            user_emails=[],
            user_groups=[],
            external_user_emails=[],
            external_user_group_ids=[],
            is_public=False,
        )

        updatable_ids = [doc.id for doc in context.updatable_docs]

        doc_id_to_access_info = get_access_for_documents(
            document_ids=updatable_ids, db_session=self.db_session
        )
        doc_id_to_document_set = {
            document_id: document_sets
            for document_id, document_sets in fetch_document_sets_for_documents(
                document_ids=updatable_ids, db_session=self.db_session
            )
        }

        doc_id_to_previous_chunk_cnt: dict[str, int] = {
            document_id: chunk_count
            for document_id, chunk_count in fetch_chunk_counts_for_documents(
                document_ids=updatable_ids,
                db_session=self.db_session,
            )
        }

        doc_id_to_new_chunk_cnt: dict[str, int] = {
            document_id: len(
                [
                    chunk
                    for chunk in chunks_with_embeddings
                    if chunk.source_document.id == document_id
                ]
            )
            for document_id in updatable_ids
        }

        # Get ancestor hierarchy node IDs for each document
        doc_id_to_ancestor_ids = self._get_ancestor_ids_for_documents(
            context.updatable_docs, tenant_id
        )

        access_aware_chunks = [
            DocMetadataAwareIndexChunk.from_index_chunk(
                index_chunk=chunk,
                access=doc_id_to_access_info.get(chunk.source_document.id, no_access),
                document_sets=set(
                    doc_id_to_document_set.get(chunk.source_document.id, [])
                ),
                user_project=[],
                boost=(
                    context.id_to_boost_map[chunk.source_document.id]
                    if chunk.source_document.id in context.id_to_boost_map
                    else DEFAULT_BOOST
                ),
                tenant_id=tenant_id,
                aggregated_chunk_boost_factor=chunk_content_scores[chunk_num],
                ancestor_hierarchy_node_ids=doc_id_to_ancestor_ids[
                    chunk.source_document.id
                ],
            )
            for chunk_num, chunk in enumerate(chunks_with_embeddings)
        ]

        return BuildMetadataAwareChunksResult(
            chunks=access_aware_chunks,
            doc_id_to_previous_chunk_cnt=doc_id_to_previous_chunk_cnt,
            doc_id_to_new_chunk_cnt=doc_id_to_new_chunk_cnt,
            user_file_id_to_raw_text={},
            user_file_id_to_token_count={},
        )

    def _get_ancestor_ids_for_documents(
        self,
        documents: list[Document],
        tenant_id: str,
    ) -> dict[str, list[int]]:
        """
        Get ancestor hierarchy node IDs for a batch of documents.

        Uses Redis cache for fast lookups - no DB calls are made unless
        there's a cache miss. Documents provide parent_hierarchy_raw_node_id
        directly from the connector.

        Returns a mapping from document_id to list of ancestor node IDs.
        """
        if not documents:
            return {}

        redis_client = get_redis_client(tenant_id=tenant_id)
        result: dict[str, list[int]] = {}

        for doc in documents:
            # Use parent_hierarchy_raw_node_id directly from the document
            # If None, get_ancestors_from_raw_id will return just the SOURCE node
            ancestors = get_ancestors_from_raw_id(
                redis_client=redis_client,
                source=doc.source,
                parent_hierarchy_raw_node_id=doc.parent_hierarchy_raw_node_id,
                db_session=self.db_session,
            )
            result[doc.id] = ancestors

        return result

    def post_index(
        self,
        context: DocumentBatchPrepareContext,
        updatable_chunk_data: list[UpdatableChunkData],
        filtered_documents: list[Document],
        result: BuildMetadataAwareChunksResult,
    ) -> None:
        """Finalize DB updates, store plaintext, and mark docs as indexed."""
        updatable_ids = [doc.id for doc in context.updatable_docs]
        last_modified_ids = []
        ids_to_new_updated_at = {}
        for doc in context.updatable_docs:
            last_modified_ids.append(doc.id)
            # doc_updated_at is the source's idea (on the other end of the connector)
            # of when the doc was last modified
            if doc.doc_updated_at is None:
                continue
            ids_to_new_updated_at[doc.id] = doc.doc_updated_at

        update_docs_updated_at__no_commit(
            ids_to_new_updated_at=ids_to_new_updated_at, db_session=self.db_session
        )

        update_docs_last_modified__no_commit(
            document_ids=last_modified_ids, db_session=self.db_session
        )

        update_docs_chunk_count__no_commit(
            document_ids=updatable_ids,
            doc_id_to_chunk_count=result.doc_id_to_new_chunk_cnt,
            db_session=self.db_session,
        )

        # these documents can now be counted as part of the CC Pairs
        # document count, so we need to mark them as indexed
        # NOTE: even documents we skipped since they were already up
        # to date should be counted here in order to maintain parity
        # between CC Pair and index attempt counts
        mark_document_as_indexed_for_cc_pair__no_commit(
            connector_id=self.index_attempt_metadata.connector_id,
            credential_id=self.index_attempt_metadata.credential_id,
            document_ids=[doc.id for doc in filtered_documents],
            db_session=self.db_session,
        )

        # save the chunk boost components to postgres
        update_chunk_boost_components__no_commit(
            chunk_data=updatable_chunk_data, db_session=self.db_session
        )

        self.db_session.commit()
