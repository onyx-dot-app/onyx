import time
from typing import List

from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock
from sqlalchemy.orm import Session
from tenacity import RetryError

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.shared.RetryDocumentIndex import RetryDocumentIndex
from onyx.background.celery.tasks.shared.tasks import LIGHT_SOFT_TIME_LIMIT
from onyx.background.celery.tasks.shared.tasks import LIGHT_TIME_LIMIT
from onyx.background.celery.tasks.shared.tasks import OnyxCeleryTaskCompletionStatus
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import CELERY_USER_FILE_FOLDER_SYNC_BEAT_LOCK_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.connector_credential_pair import (
    get_connector_credential_pairs_with_user_files,
)
from onyx.db.document import get_document
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.search_settings import get_active_search_settings
from onyx.db.user_documents import fetch_user_files_for_documents
from onyx.db.user_documents import fetch_user_folders_for_documents
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import VespaDocumentUserFields
from onyx.httpx.httpx_pool import HttpxPool
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


@shared_task(
    name=OnyxCeleryTask.CHECK_FOR_USER_FILE_FOLDER_SYNC,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    trail=False,
    bind=True,
)
def check_for_user_file_folder_sync(self: Task, *, tenant_id: str) -> bool | None:
    """Runs periodically to check for documents that need user file folder metadata updates.
    This task fetches all connector credential pairs with user files, gets the documents
    associated with them, and updates the user file and folder metadata in Vespa.
    """

    time_start = time.monotonic()

    r = get_redis_client()

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_USER_FILE_FOLDER_SYNC_BEAT_LOCK,
        timeout=CELERY_USER_FILE_FOLDER_SYNC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        with get_session_with_current_tenant() as db_session:
            # Get all connector credential pairs that have user files
            cc_pairs = get_connector_credential_pairs_with_user_files(db_session)

            if not cc_pairs:
                task_logger.info("No connector credential pairs with user files found")
                return True

            # Get all documents associated with these cc_pairs
            document_ids = get_documents_for_cc_pairs(cc_pairs, db_session)

            if not document_ids:
                task_logger.info(
                    "No documents found for connector credential pairs with user files"
                )
                return True

            # Fetch current user file and folder IDs for these documents
            doc_id_to_user_file_id = fetch_user_files_for_documents(
                document_ids=document_ids, db_session=db_session
            )
            doc_id_to_user_folder_id = fetch_user_folders_for_documents(
                document_ids=document_ids, db_session=db_session
            )

            # Update Vespa metadata for each document
            for doc_id in document_ids:
                user_file_id = doc_id_to_user_file_id.get(doc_id)
                user_folder_id = doc_id_to_user_folder_id.get(doc_id)

                if user_file_id is not None or user_folder_id is not None:
                    # Schedule a task to update the document metadata
                    update_user_file_folder_metadata.apply_async(
                        args=(doc_id,),  # Use tuple instead of list for args
                        kwargs={
                            "tenant_id": tenant_id,
                            "user_file_id": user_file_id,
                            "user_folder_id": user_folder_id,
                        },
                        queue="vespa_metadata_sync",
                    )

            task_logger.info(
                f"Scheduled metadata updates for {len(document_ids)} documents. "
                f"Elapsed time: {time.monotonic() - time_start:.2f}s"
            )

            return True
    except Exception as e:
        task_logger.exception(f"Error in check_for_user_file_folder_sync: {e}")
        return False
    finally:
        lock_beat.release()


def get_documents_for_cc_pairs(
    cc_pairs: List[ConnectorCredentialPair], db_session: Session
) -> List[str]:
    """Get all document IDs associated with the given connector credential pairs."""
    if not cc_pairs:
        return []

    cc_pair_ids = [cc_pair.id for cc_pair in cc_pairs]

    # Query to get document IDs from DocumentByConnectorCredentialPair
    # Note: DocumentByConnectorCredentialPair uses connector_id and credential_id, not cc_pair_id
    doc_cc_pairs = (
        db_session.query(Document.id)
        .join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
        )
        .filter(
            db_session.query(ConnectorCredentialPair)
            .filter(
                ConnectorCredentialPair.id.in_(cc_pair_ids),
                ConnectorCredentialPair.connector_id
                == DocumentByConnectorCredentialPair.connector_id,
                ConnectorCredentialPair.credential_id
                == DocumentByConnectorCredentialPair.credential_id,
            )
            .exists()
        )
        .all()
    )

    return [doc_id for (doc_id,) in doc_cc_pairs]


@shared_task(
    name=OnyxCeleryTask.UPDATE_USER_FILE_FOLDER_METADATA,
    bind=True,
    soft_time_limit=LIGHT_SOFT_TIME_LIMIT,
    time_limit=LIGHT_TIME_LIMIT,
    max_retries=3,
)
def update_user_file_folder_metadata(
    self: Task,
    document_id: str,
    *,
    tenant_id: str,
    user_file_id: int | None,
    user_folder_id: int | None,
) -> bool:
    """Updates the user file and folder metadata for a document in Vespa."""
    start = time.monotonic()
    completion_status = OnyxCeleryTaskCompletionStatus.UNDEFINED

    try:
        with get_session_with_current_tenant() as db_session:
            active_search_settings = get_active_search_settings(db_session)
            doc_index = get_default_document_index(
                search_settings=active_search_settings.primary,
                secondary_search_settings=active_search_settings.secondary,
                httpx_client=HttpxPool.get("vespa"),
            )

            retry_index = RetryDocumentIndex(doc_index)

            doc = get_document(document_id, db_session)
            if not doc:
                elapsed = time.monotonic() - start
                task_logger.info(
                    f"doc={document_id} "
                    f"action=no_operation "
                    f"elapsed={elapsed:.2f}"
                )
                completion_status = OnyxCeleryTaskCompletionStatus.SKIPPED
                return False

            # Create user fields object with file and folder IDs
            user_fields = VespaDocumentUserFields(
                user_file_id=str(user_file_id) if user_file_id is not None else None,
                user_folder_id=(
                    str(user_folder_id) if user_folder_id is not None else None
                ),
            )

            # Update Vespa. OK if doc doesn't exist. Raises exception otherwise.
            chunks_affected = retry_index.update_single(
                document_id,
                tenant_id=tenant_id,
                chunk_count=doc.chunk_count,
                fields=None,  # We're only updating user fields
                user_fields=user_fields,
            )

            elapsed = time.monotonic() - start
            task_logger.info(
                f"doc={document_id} "
                f"action=user_file_folder_sync "
                f"user_file_id={user_file_id} "
                f"user_folder_id={user_folder_id} "
                f"chunks={chunks_affected} "
                f"elapsed={elapsed:.2f}"
            )
            completion_status = OnyxCeleryTaskCompletionStatus.SUCCEEDED
            return True

    except SoftTimeLimitExceeded:
        task_logger.info(f"SoftTimeLimitExceeded exception. doc={document_id}")
        completion_status = OnyxCeleryTaskCompletionStatus.SOFT_TIME_LIMIT
    except Exception as ex:
        e: Exception | None = None
        while True:
            if isinstance(ex, RetryError):
                task_logger.warning(
                    f"Tenacity retry failed: num_attempts={ex.last_attempt.attempt_number}"
                )

                # only set the inner exception if it is of type Exception
                e_temp = ex.last_attempt.exception()
                if isinstance(e_temp, Exception):
                    e = e_temp
            else:
                e = ex

            task_logger.exception(
                f"update_user_file_folder_metadata exceptioned: doc={document_id}"
            )

            completion_status = OnyxCeleryTaskCompletionStatus.RETRYABLE_EXCEPTION
            if (
                self.max_retries is not None
                and self.request.retries >= self.max_retries
            ):
                completion_status = (
                    OnyxCeleryTaskCompletionStatus.NON_RETRYABLE_EXCEPTION
                )

            # Exponential backoff from 2^4 to 2^6 ... i.e. 16, 32, 64
            countdown = 2 ** (self.request.retries + 4)
            self.retry(exc=e, countdown=countdown)  # this will raise a celery exception
            break  # we won't hit this, but it looks weird not to have it
    finally:
        task_logger.info(
            f"update_user_file_folder_metadata completed: status={completion_status.value} doc={document_id}"
        )

    return False
