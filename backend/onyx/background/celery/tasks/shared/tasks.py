import time
from enum import Enum
from http import HTTPStatus

import httpx
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from tenacity import RetryError

from onyx.access.access import get_access_for_document
from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.shared.RetryDocumentIndex import RetryDocumentIndex
from onyx.configs.constants import ONYX_CELERY_BEAT_HEARTBEAT_KEY
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.document import delete_document_by_connector_credential_pair__no_commit
from onyx.db.document import delete_documents_complete__no_commit
from onyx.db.document import fetch_chunk_count_for_document
from onyx.db.document import get_document
from onyx.db.document import get_document_connector_count
from onyx.db.document import mark_document_as_modified
from onyx.db.document import mark_document_as_synced
from onyx.db.document_set import fetch_document_sets_for_document
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.relationships import delete_document_references_from_kg
from onyx.db.search_settings import get_active_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import VespaDocumentFields
from onyx.httpx.httpx_pool import HttpxPool
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import ConnectorCredentialPairIdentifier

DOCUMENT_BY_CC_PAIR_CLEANUP_MAX_RETRIES = 3


# 5 seconds more than RetryDocumentIndex STOP_AFTER+MAX_WAIT
LIGHT_SOFT_TIME_LIMIT = 105
LIGHT_TIME_LIMIT = LIGHT_SOFT_TIME_LIMIT + 15


class OnyxCeleryTaskCompletionStatus(str, Enum):
    """The different statuses the watchdog can finish with.

    TODO: create broader success/failure/abort categories
    """

    UNDEFINED = "undefined"

    SUCCEEDED = "succeeded"

    SKIPPED = "skipped"

    SOFT_TIME_LIMIT = "soft_time_limit"

    NON_RETRYABLE_EXCEPTION = "non_retryable_exception"
    RETRYABLE_EXCEPTION = "retryable_exception"


@shared_task(
    name=OnyxCeleryTask.DOCUMENT_BY_CC_PAIR_CLEANUP_TASK,
    soft_time_limit=LIGHT_SOFT_TIME_LIMIT,
    time_limit=LIGHT_TIME_LIMIT,
    max_retries=DOCUMENT_BY_CC_PAIR_CLEANUP_MAX_RETRIES,
    bind=True,
)
def document_by_cc_pair_cleanup_task(
    self: Task,
    document_id: str,
    connector_id: int,
    credential_id: int,
    tenant_id: str,
) -> bool:
    """A lightweight subtask used to clean up document to cc pair relationships.
    Created by connection deletion and connector pruning parent tasks."""

    """
    To delete a connector / credential pair:
    (1) find all documents associated with connector / credential pair where there
    this the is only connector / credential pair that has indexed it
    (2) delete all documents from document stores
    (3) delete all entries from postgres
    (4) find all documents associated with connector / credential pair where there
    are multiple connector / credential pairs that have indexed it
    (5) update document store entries to remove access associated with the
    connector / credential pair from the access list
    (6) delete all relevant entries from postgres
    """
    task_logger.debug(f"Task start: doc={document_id}")

    start = time.monotonic()

    completion_status = OnyxCeleryTaskCompletionStatus.UNDEFINED

    try:
        with get_session_with_current_tenant() as db_session:
            action = "skip"
            chunks_affected = 0

            active_search_settings = get_active_search_settings(db_session)
            doc_index = get_default_document_index(
                active_search_settings.primary,
                active_search_settings.secondary,
                httpx_client=HttpxPool.get("vespa"),
            )

            retry_index = RetryDocumentIndex(doc_index)

            count = get_document_connector_count(db_session, document_id)
            if count == 1:
                # count == 1 means this is the only remaining cc_pair reference to the doc
                # delete it from vespa and the db
                action = "delete"

                chunk_count = fetch_chunk_count_for_document(document_id, db_session)

                chunks_affected = retry_index.delete_single(
                    document_id,
                    tenant_id=tenant_id,
                    chunk_count=chunk_count,
                )

                delete_document_references_from_kg(
                    db_session=db_session,
                    document_id=document_id,
                )

                delete_documents_complete__no_commit(
                    db_session=db_session,
                    document_ids=[document_id],
                )
                db_session.commit()

                completion_status = OnyxCeleryTaskCompletionStatus.SUCCEEDED
            elif count > 1:
                action = "update"

                # count > 1 means the document still has cc_pair references
                doc = get_document(document_id, db_session)
                if not doc:
                    return False

                # the below functions do not include cc_pairs being deleted.
                # i.e. they will correctly omit access for the current cc_pair
                doc_access = get_access_for_document(
                    document_id=document_id, db_session=db_session
                )

                doc_sets = fetch_document_sets_for_document(document_id, db_session)
                update_doc_sets: set[str] = set(doc_sets)

                fields = VespaDocumentFields(
                    document_sets=update_doc_sets,
                    access=doc_access,
                    boost=doc.boost,
                    hidden=doc.hidden,
                )

                # update Vespa. OK if doc doesn't exist. Raises exception otherwise.
                chunks_affected = retry_index.update_single(
                    document_id,
                    tenant_id=tenant_id,
                    chunk_count=doc.chunk_count,
                    fields=fields,
                    user_fields=None,
                )

                # there are still other cc_pair references to the doc, so just resync to Vespa
                delete_document_by_connector_credential_pair__no_commit(
                    db_session=db_session,
                    document_id=document_id,
                    connector_credential_pair_identifier=ConnectorCredentialPairIdentifier(
                        connector_id=connector_id,
                        credential_id=credential_id,
                    ),
                )

                mark_document_as_synced(document_id, db_session)
                db_session.commit()

                completion_status = OnyxCeleryTaskCompletionStatus.SUCCEEDED
            else:
                completion_status = OnyxCeleryTaskCompletionStatus.SKIPPED

            elapsed = time.monotonic() - start
            task_logger.info(
                f"doc={document_id} "
                f"action={action} "
                f"refcount={count} "
                f"chunks={chunks_affected} "
                f"elapsed={elapsed:.2f}"
            )
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

            if isinstance(e, httpx.HTTPStatusError):
                if e.response.status_code == HTTPStatus.BAD_REQUEST:
                    task_logger.exception(
                        f"Non-retryable HTTPStatusError: "
                        f"doc={document_id} "
                        f"status={e.response.status_code}"
                    )
                completion_status = (
                    OnyxCeleryTaskCompletionStatus.NON_RETRYABLE_EXCEPTION
                )
                break

            task_logger.exception(
                f"document_by_cc_pair_cleanup_task exceptioned: doc={document_id}"
            )

            completion_status = OnyxCeleryTaskCompletionStatus.RETRYABLE_EXCEPTION
            if (
                self.max_retries is not None
                and self.request.retries >= self.max_retries
            ):
                # This is the last attempt! mark the document as dirty in the db so that it
                # eventually gets fixed out of band via stale document reconciliation
                task_logger.warning(
                    f"Max celery task retries reached. Marking doc as dirty for reconciliation: "
                    f"doc={document_id}"
                )
                with get_session_with_current_tenant() as db_session:
                    # delete the cc pair relationship now and let reconciliation clean it up
                    # in vespa
                    delete_document_by_connector_credential_pair__no_commit(
                        db_session=db_session,
                        document_id=document_id,
                        connector_credential_pair_identifier=ConnectorCredentialPairIdentifier(
                            connector_id=connector_id,
                            credential_id=credential_id,
                        ),
                    )
                    mark_document_as_modified(document_id, db_session)
                completion_status = (
                    OnyxCeleryTaskCompletionStatus.NON_RETRYABLE_EXCEPTION
                )
                break

            # Exponential backoff from 2^4 to 2^6 ... i.e. 16, 32, 64
            countdown = 2 ** (self.request.retries + 4)
            self.retry(exc=e, countdown=countdown)  # this will raise a celery exception
            break  # we won't hit this, but it looks weird not to have it
    finally:
        task_logger.info(
            f"document_by_cc_pair_cleanup_task completed: status={completion_status.value} doc={document_id}"
        )

    if completion_status != OnyxCeleryTaskCompletionStatus.SUCCEEDED:
        return False

    task_logger.info(f"document_by_cc_pair_cleanup_task finished: doc={document_id}")
    return True


@shared_task(name=OnyxCeleryTask.CELERY_BEAT_HEARTBEAT, ignore_result=True, bind=True)
def celery_beat_heartbeat(self: Task, *, tenant_id: str) -> None:
    """When this task runs, it writes a key to Redis with a TTL.

    An external observer can check this key to figure out if the celery beat is still running.
    """
    time_start = time.monotonic()
    r: Redis = get_redis_client()
    r.set(ONYX_CELERY_BEAT_HEARTBEAT_KEY, 1, ex=600)
    time_elapsed = time.monotonic() - time_start
    task_logger.info(f"celery_beat_heartbeat finished: " f"elapsed={time_elapsed:.2f}")
