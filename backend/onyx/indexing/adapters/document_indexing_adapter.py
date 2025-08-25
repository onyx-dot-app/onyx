import contextlib
import time
from collections.abc import Generator

from sqlalchemy.engine.util import TransactionalContext
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.access.access import get_access_for_documents
from onyx.access.models import DocumentAccess
from onyx.configs.constants import DEFAULT_BOOST
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.chunk import update_chunk_boost_components__no_commit
from onyx.db.document import acquire_document_locks
from onyx.db.document import fetch_chunk_counts_for_documents
from onyx.db.document import mark_document_as_indexed_for_cc_pair__no_commit
from onyx.db.document import update_docs_chunk_count__no_commit
from onyx.db.document import update_docs_last_modified__no_commit
from onyx.db.document import update_docs_updated_at__no_commit
from onyx.db.document_set import fetch_document_sets_for_documents
from onyx.db.user_documents import fetch_user_files_for_documents
from onyx.db.user_documents import fetch_user_folders_for_documents
from onyx.db.user_documents import update_user_file_token_count__no_commit
from onyx.file_store.utils import store_user_file_plaintext
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from onyx.indexing.models import BuildMetadataAwareChunksResult
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk
from onyx.indexing.models import UpdatableChunkData
from onyx.llm.factory import get_default_llms
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger

logger = setup_logger()
_NUM_LOCK_ATTEMPTS = 10
_LOCK_RETRY_DELAY = 10


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
        """Try and acquire locks for the documents to prevent other jobs from
        modifying them at the same time (e.g. avoid race conditions). This should be
        called ahead of any modification to Vespa. Locks should be released by the
        caller as soon as updates are complete by finishing the transaction.

        NOTE: only one commit is allowed within the context manager returned by this function.
        Multiple commits will result in a sqlalchemy.exc.InvalidRequestError.
        NOTE: this function will commit any existing transaction.
        """

        self.db_session.commit()  # ensure that we're not in a transaction

        lock_acquired = False
        for i in range(_NUM_LOCK_ATTEMPTS):
            try:
                with self.db_session.begin() as transaction:
                    lock_acquired = acquire_document_locks(
                        db_session=self.db_session,
                        document_ids=[doc.id for doc in documents],
                    )
                    if lock_acquired:
                        yield transaction
                        break
            except OperationalError as e:
                logger.warning(
                    f"Failed to acquire locks for documents on attempt {i}, retrying. Error: {e}"
                )

            time.sleep(_LOCK_RETRY_DELAY)

        if not lock_acquired:
            raise RuntimeError(
                f"Failed to acquire locks after {_NUM_LOCK_ATTEMPTS} attempts "
                f"for documents: {[doc.id for doc in documents]}"
            )

    def build_metadata_aware_chunks(
        self,
        chunks_with_embeddings: list[IndexChunk],
        chunk_content_scores: list[float],
        tenant_id: str,
        context: DocumentBatchPrepareContext,
    ) -> BuildMetadataAwareChunksResult:
        """Enrich chunks with access, document sets, boosts and token counts."""

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

        doc_id_to_user_file_id: dict[str, int | None] = fetch_user_files_for_documents(
            document_ids=updatable_ids, db_session=self.db_session
        )
        doc_id_to_user_folder_id: dict[str, int | None] = (
            fetch_user_folders_for_documents(
                document_ids=updatable_ids, db_session=self.db_session
            )
        )

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

        try:
            llm, _ = get_default_llms()

            llm_tokenizer = get_tokenizer(
                model_name=llm.config.model_name,
                provider_type=llm.config.model_provider,
            )
        except Exception as e:
            logger.error(f"Error getting tokenizer: {e}")
            llm_tokenizer = None

        # Calculate token counts for each document by combining all its chunks' content
        user_file_id_to_token_count: dict[int, int | None] = {}
        user_file_id_to_raw_text: dict[int, str] = {}
        for document_id in updatable_ids:
            # Only calculate token counts for documents that have a user file ID

            user_file_id = doc_id_to_user_file_id.get(document_id)
            if user_file_id is None:
                continue

            document_chunks = [
                chunk
                for chunk in chunks_with_embeddings
                if chunk.source_document.id == document_id
            ]
            if document_chunks:
                combined_content = " ".join(
                    [chunk.content for chunk in document_chunks]
                )
                token_count = (
                    len(llm_tokenizer.encode(combined_content)) if llm_tokenizer else 0
                )
                user_file_id_to_token_count[user_file_id] = token_count
                user_file_id_to_raw_text[user_file_id] = combined_content
            else:
                user_file_id_to_token_count[user_file_id] = None

        # we're concerned about race conditions where multiple simultaneous indexings might result
        # in one set of metadata overwriting another one in vespa.
        # we still write data here for the immediate and most likely correct sync, but
        # to resolve this, an update of the last modified field at the end of this loop
        # always triggers a final metadata sync via the celery queue
        access_aware_chunks = [
            DocMetadataAwareIndexChunk.from_index_chunk(
                index_chunk=chunk,
                access=doc_id_to_access_info.get(chunk.source_document.id, no_access),
                document_sets=set(
                    doc_id_to_document_set.get(chunk.source_document.id, [])
                ),
                user_file=doc_id_to_user_file_id.get(chunk.source_document.id, None),
                user_folder=doc_id_to_user_folder_id.get(
                    chunk.source_document.id, None
                ),
                boost=(
                    context.id_to_db_doc_map[chunk.source_document.id].boost
                    if chunk.source_document.id in context.id_to_db_doc_map
                    else DEFAULT_BOOST
                ),
                tenant_id=tenant_id,
                aggregated_chunk_boost_factor=chunk_content_scores[chunk_num],
            )
            for chunk_num, chunk in enumerate(chunks_with_embeddings)
        ]

        return BuildMetadataAwareChunksResult(
            chunks=access_aware_chunks,
            doc_id_to_previous_chunk_cnt=doc_id_to_previous_chunk_cnt,
            doc_id_to_new_chunk_cnt=doc_id_to_new_chunk_cnt,
            user_file_id_to_raw_text=user_file_id_to_raw_text,
            user_file_id_to_token_count=user_file_id_to_token_count,
        )

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

        # Store the plaintext in the file store for faster retrieval
        # NOTE: this creates its own session to avoid committing the overall
        # transaction.
        for user_file_id, raw_text in result.user_file_id_to_raw_text.items():
            store_user_file_plaintext(
                user_file_id=user_file_id,
                plaintext_content=raw_text,
            )

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

        update_user_file_token_count__no_commit(
            user_file_id_to_token_count=result.user_file_id_to_token_count,
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
