import contextlib
import datetime
import time
from collections.abc import Generator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import TransactionalContext

from onyx.access.access import get_access_for_user_files
from onyx.access.models import DocumentAccess
from onyx.configs.constants import DEFAULT_BOOST
from onyx.connectors.models import Document
from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.db.user_file import fetch_chunk_counts_for_user_files
from onyx.db.user_file import fetch_user_project_ids_for_user_files
from onyx.file_store.utils import store_user_file_plaintext
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.models import BuildMetadataAwareChunksResult
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk
from onyx.indexing.models import UpdatableChunkData
from onyx.llm.factory import get_default_llms
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.utils.logger import setup_logger

logger = setup_logger()

_NUM_LOCK_ATTEMPTS = 3
retry_delay = 0.5


def _acquire_user_file_locks(db_session: Session, user_file_ids: list[str]) -> bool:
    """Acquire locks for the specified user files."""
    # Convert to UUIDs for the DB comparison
    user_file_uuid_list = [UUID(user_file_id) for user_file_id in user_file_ids]
    stmt = (
        select(UserFile.id)
        .where(UserFile.id.in_(user_file_uuid_list))
        .with_for_update(nowait=True)
    )
    # will raise exception if any of the documents are already locked
    documents = db_session.scalars(stmt).all()

    # make sure we found every document
    if len(documents) != len(set(user_file_ids)):
        logger.warning("Didn't find row for all specified user file IDs. Aborting.")
        return False

    return True


class UserFileIndexingAdapter:
    def __init__(self, tenant_id: str, db_session: Session):
        self.tenant_id = tenant_id
        self.db_session = db_session

    def prepare(
        self, documents: list[Document], ignore_time_skip: bool
    ) -> DocumentBatchPrepareContext:
        return DocumentBatchPrepareContext(
            updatable_docs=documents, id_to_boost_map={}  # TODO(subash): add boost map
        )

    @contextlib.contextmanager
    def lock_context(
        self, documents: list[Document]
    ) -> Generator[TransactionalContext, None, None]:
        self.db_session.commit()  # ensure that we're not in a transaction
        lock_acquired = False
        for i in range(_NUM_LOCK_ATTEMPTS):
            try:
                with self.db_session.begin() as transaction:
                    lock_acquired = _acquire_user_file_locks(
                        db_session=self.db_session,
                        user_file_ids=[doc.id for doc in documents],
                    )
                    if lock_acquired:
                        yield transaction
                        break
            except OperationalError as e:
                logger.warning(
                    f"Failed to acquire locks for user files on attempt {i}, retrying. Error: {e}"
                )

            time.sleep(retry_delay)

        if not lock_acquired:
            raise RuntimeError(
                f"Failed to acquire locks after {_NUM_LOCK_ATTEMPTS} attempts "
                f"for user files: {[doc.id for doc in documents]}"
            )

    def build_metadata_aware_chunks(
        self,
        chunks_with_embeddings: list[IndexChunk],
        chunk_content_scores: list[float],
        tenant_id: str,
        context: DocumentBatchPrepareContext,
    ) -> BuildMetadataAwareChunksResult:

        no_access = DocumentAccess.build(
            user_emails=[],
            user_groups=[],
            external_user_emails=[],
            external_user_group_ids=[],
            is_public=False,
        )

        updatable_ids = [doc.id for doc in context.updatable_docs]
        user_file_id_to_project_ids = fetch_user_project_ids_for_user_files(
            user_file_ids=updatable_ids,
            db_session=self.db_session,
        )
        user_file_id_to_access: dict[str, DocumentAccess] = get_access_for_user_files(
            user_file_ids=updatable_ids,
            db_session=self.db_session,
        )
        user_file_id_to_previous_chunk_cnt: dict[str, int] = {
            user_file_id: chunk_count
            for user_file_id, chunk_count in fetch_chunk_counts_for_user_files(
                user_file_ids=updatable_ids,
                db_session=self.db_session,
            )
        }

        user_file_id_to_new_chunk_cnt: dict[str, int] = {
            user_file_id: len(
                [
                    chunk
                    for chunk in chunks_with_embeddings
                    if chunk.source_document.id == user_file_id
                ]
            )
            for user_file_id in updatable_ids
        }

        # Initialize tokenizer used for token count calculation
        try:
            llm, _ = get_default_llms()
            llm_tokenizer = get_tokenizer(
                model_name=llm.config.model_name,
                provider_type=llm.config.model_provider,
            )
        except Exception as e:
            logger.error(f"Error getting tokenizer: {e}")
            llm_tokenizer = None

        user_file_id_to_raw_text: dict[str, str] = {}
        user_file_id_to_token_count: dict[str, int | None] = {}
        for user_file_id in updatable_ids:
            user_file_chunks = [
                chunk
                for chunk in chunks_with_embeddings
                if chunk.source_document.id == user_file_id
            ]
            if user_file_chunks:
                combined_content = " ".join(
                    [chunk.content for chunk in user_file_chunks]
                )
                user_file_id_to_raw_text[str(user_file_id)] = combined_content
                token_count = (
                    len(llm_tokenizer.encode(combined_content)) if llm_tokenizer else 0
                )
                user_file_id_to_token_count[str(user_file_id)] = token_count
            else:
                user_file_id_to_raw_text[str(user_file_id)] = ""
                user_file_id_to_token_count[str(user_file_id)] = None

        access_aware_chunks = [
            DocMetadataAwareIndexChunk.from_index_chunk(
                index_chunk=chunk,
                access=user_file_id_to_access.get(chunk.source_document.id, no_access),
                document_sets=set(),
                user_project=user_file_id_to_project_ids.get(
                    chunk.source_document.id, []
                ),
                # we are going to index userfiles only once, so we just set the boost to the default
                boost=DEFAULT_BOOST,
                tenant_id=tenant_id,
                aggregated_chunk_boost_factor=chunk_content_scores[chunk_num],
            )
            for chunk_num, chunk in enumerate(chunks_with_embeddings)
        ]

        return BuildMetadataAwareChunksResult(
            chunks=access_aware_chunks,
            doc_id_to_previous_chunk_cnt=user_file_id_to_previous_chunk_cnt,
            doc_id_to_new_chunk_cnt=user_file_id_to_new_chunk_cnt,
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
        user_file_ids = [doc.id for doc in context.updatable_docs]

        user_files = (
            self.db_session.query(UserFile).filter(UserFile.id.in_(user_file_ids)).all()
        )
        for user_file in user_files:
            # don't update the status if the user file is being deleted
            if user_file.status != UserFileStatus.DELETING:
                user_file.status = UserFileStatus.COMPLETED
            user_file.last_project_sync_at = datetime.datetime.now(
                datetime.timezone.utc
            )
            user_file.chunk_count = result.doc_id_to_new_chunk_cnt[str(user_file.id)]
            user_file.token_count = result.user_file_id_to_token_count[
                str(user_file.id)
            ]
        self.db_session.commit()

        # Store the plaintext in the file store for faster retrieval
        # NOTE: this creates its own session to avoid committing the overall
        # transaction.
        for user_file_id, raw_text in result.user_file_id_to_raw_text.items():
            store_user_file_plaintext(
                user_file_id=UUID(user_file_id),
                plaintext_content=raw_text,
            )
