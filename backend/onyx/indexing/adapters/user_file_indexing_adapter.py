from __future__ import annotations

import contextlib
import datetime
import time
from collections import defaultdict
from collections.abc import Generator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import TransactionalContext

from onyx.access.access import get_access_for_user_files
from onyx.access.models import DocumentAccess
from onyx.configs.constants import DEFAULT_BOOST
from onyx.configs.constants import NotificationType
from onyx.connectors.models import Document
from onyx.db.enums import UserFileStatus
from onyx.db.models import Persona
from onyx.db.models import UserFile
from onyx.db.notification import create_notification
from onyx.db.user_file import fetch_chunk_counts_for_user_files
from onyx.db.user_file import fetch_persona_ids_for_user_files
from onyx.db.user_file import fetch_user_project_ids_for_user_files
from onyx.file_store.utils import store_user_file_plaintext
from onyx.indexing.indexing_pipeline import DocumentBatchPrepareContext
from onyx.indexing.models import DocAwareChunk
from onyx.indexing.models import DocMetadataAwareIndexChunk
from onyx.indexing.models import IndexChunk
from onyx.indexing.models import UpdatableChunkData
from onyx.llm.factory import get_default_llm
from onyx.natural_language_processing.utils import count_tokens
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
        self,
        documents: list[Document],
        ignore_time_skip: bool,  # noqa: ARG002
    ) -> DocumentBatchPrepareContext:
        return DocumentBatchPrepareContext(
            updatable_docs=documents,
            id_to_boost_map={},  # TODO(subash): add boost map
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
                f"Failed to acquire locks after {_NUM_LOCK_ATTEMPTS} attempts for user files: {[doc.id for doc in documents]}"
            )

    def prepare_enrichment(
        self,
        context: DocumentBatchPrepareContext,
        tenant_id: str,
        chunks: list[DocAwareChunk],
    ) -> UserFileChunkEnricher:
        """Do all DB lookups and pre-compute file metadata from chunks."""
        updatable_ids = [doc.id for doc in context.updatable_docs]

        doc_id_to_new_chunk_cnt: dict[str, int] = defaultdict(int)
        content_by_file: dict[str, list[str]] = defaultdict(list)
        for chunk in chunks:
            doc_id_to_new_chunk_cnt[chunk.source_document.id] += 1
            content_by_file[chunk.source_document.id].append(chunk.content)

        no_access = DocumentAccess.build(
            user_emails=[],
            user_groups=[],
            external_user_emails=[],
            external_user_group_ids=[],
            is_public=False,
        )

        user_file_id_to_project_ids = fetch_user_project_ids_for_user_files(
            user_file_ids=updatable_ids,
            db_session=self.db_session,
        )
        user_file_id_to_persona_ids = fetch_persona_ids_for_user_files(
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

        # Initialize tokenizer used for token count calculation
        try:
            llm = get_default_llm()
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
            contents = content_by_file.get(user_file_id)
            if contents:
                combined_content = " ".join(contents)
                user_file_id_to_raw_text[str(user_file_id)] = combined_content
                token_count: int = (
                    count_tokens(combined_content, llm_tokenizer)
                    if llm_tokenizer
                    else 0
                )
                user_file_id_to_token_count[str(user_file_id)] = token_count
            else:
                user_file_id_to_raw_text[str(user_file_id)] = ""
                user_file_id_to_token_count[str(user_file_id)] = None

        return UserFileChunkEnricher(
            user_file_id_to_access=user_file_id_to_access,
            user_file_id_to_project_ids=user_file_id_to_project_ids,
            user_file_id_to_persona_ids=user_file_id_to_persona_ids,
            doc_id_to_previous_chunk_cnt=user_file_id_to_previous_chunk_cnt,
            doc_id_to_new_chunk_cnt=dict(doc_id_to_new_chunk_cnt),
            user_file_id_to_raw_text=user_file_id_to_raw_text,
            user_file_id_to_token_count=user_file_id_to_token_count,
            no_access=no_access,
            tenant_id=tenant_id,
        )

    def _notify_assistant_owners_if_files_ready(
        self, user_files: list[UserFile]
    ) -> None:
        """
        Check if all files for associated assistants are processed and notify owners.
        Only sends notification when all files for an assistant are COMPLETED.
        """
        for user_file in user_files:
            if user_file.status == UserFileStatus.COMPLETED:
                for assistant in user_file.assistants:
                    # Skip assistants without owners
                    if assistant.user_id is None:
                        continue

                    # Check if all OTHER files for this assistant are completed
                    # (we already know current file is completed from the outer check)
                    all_files_completed = all(
                        f.status == UserFileStatus.COMPLETED
                        for f in assistant.user_files
                        if f.id != user_file.id
                    )

                    if all_files_completed:
                        create_notification(
                            user_id=assistant.user_id,
                            notif_type=NotificationType.ASSISTANT_FILES_READY,
                            db_session=self.db_session,
                            title="Your files are ready!",
                            description=f"All files for agent {assistant.name} have been processed and are now available.",
                            additional_data={
                                "persona_id": assistant.id,
                                "link": f"/assistants/{assistant.id}",
                            },
                            autocommit=False,
                        )

    def post_index(
        self,
        context: DocumentBatchPrepareContext,
        updatable_chunk_data: list[UpdatableChunkData],  # noqa: ARG002
        filtered_documents: list[Document],  # noqa: ARG002
        enrichment: UserFileChunkEnricher,
    ) -> None:
        user_file_ids = [doc.id for doc in context.updatable_docs]

        user_files = (
            self.db_session.query(UserFile)
            .options(selectinload(UserFile.assistants).selectinload(Persona.user_files))
            .filter(UserFile.id.in_(user_file_ids))
            .all()
        )
        for user_file in user_files:
            # don't update the status if the user file is being deleted
            if user_file.status != UserFileStatus.DELETING:
                user_file.status = UserFileStatus.COMPLETED
            user_file.last_project_sync_at = datetime.datetime.now(
                datetime.timezone.utc
            )
            user_file.chunk_count = enrichment.doc_id_to_new_chunk_cnt[
                str(user_file.id)
            ]
            user_file.token_count = enrichment.user_file_id_to_token_count[
                str(user_file.id)
            ]

        # Notify assistant owners if all their files are now processed
        self._notify_assistant_owners_if_files_ready(user_files)

        self.db_session.commit()

        # Store the plaintext in the file store for faster retrieval
        # NOTE: this creates its own session to avoid committing the overall
        # transaction.
        for user_file_id, raw_text in enrichment.user_file_id_to_raw_text.items():
            store_user_file_plaintext(
                user_file_id=UUID(user_file_id),
                plaintext_content=raw_text,
            )


class UserFileChunkEnricher:
    """Pre-computed metadata for per-chunk enrichment of user-uploaded files."""

    def __init__(
        self,
        user_file_id_to_access: dict[str, DocumentAccess],
        user_file_id_to_project_ids: dict[str, list[int]],
        user_file_id_to_persona_ids: dict[str, list[int]],
        doc_id_to_previous_chunk_cnt: dict[str, int],
        doc_id_to_new_chunk_cnt: dict[str, int],
        user_file_id_to_raw_text: dict[str, str],
        user_file_id_to_token_count: dict[str, int | None],
        no_access: DocumentAccess,
        tenant_id: str,
    ) -> None:
        self._user_file_id_to_access = user_file_id_to_access
        self._user_file_id_to_project_ids = user_file_id_to_project_ids
        self._user_file_id_to_persona_ids = user_file_id_to_persona_ids
        self._no_access = no_access
        self._tenant_id = tenant_id
        self.doc_id_to_previous_chunk_cnt = doc_id_to_previous_chunk_cnt
        self.doc_id_to_new_chunk_cnt = doc_id_to_new_chunk_cnt
        self.user_file_id_to_raw_text = user_file_id_to_raw_text
        self.user_file_id_to_token_count = user_file_id_to_token_count

    def enrich_chunk(
        self, chunk: IndexChunk, score: float
    ) -> DocMetadataAwareIndexChunk:
        return DocMetadataAwareIndexChunk.from_index_chunk(
            index_chunk=chunk,
            access=self._user_file_id_to_access.get(
                chunk.source_document.id, self._no_access
            ),
            document_sets=set(),
            user_project=self._user_file_id_to_project_ids.get(
                chunk.source_document.id, []
            ),
            personas=self._user_file_id_to_persona_ids.get(
                chunk.source_document.id, []
            ),
            boost=DEFAULT_BOOST,
            tenant_id=self._tenant_id,
            aggregated_chunk_boost_factor=score,
        )
