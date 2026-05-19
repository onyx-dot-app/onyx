import random
import time
from enum import Enum
from http import HTTPStatus

import httpx
from celery import shared_task
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from tenacity import RetryError

from onyx.access.access import get_access_for_document
from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.shared.RetryDocumentIndex import RetryDocumentIndex
from onyx.configs.constants import ONYX_CELERY_BEAT_HEARTBEAT_KEY
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.document import delete_document_by_connector_credential_pair__no_commit
from onyx.db.document import delete_documents_by_connector_credential_pair__no_commit
from onyx.db.document import delete_documents_complete
from onyx.db.document import fetch_chunk_count_for_document
from onyx.db.document import fetch_chunk_counts_for_documents
from onyx.db.document import get_document
from onyx.db.document import get_document_connector_count
from onyx.db.document import get_document_connector_counts
from onyx.db.document import mark_document_as_modified
from onyx.db.document import mark_document_as_synced
from onyx.db.document import mark_documents_as_modified
from onyx.db.document import mark_documents_as_synced
from onyx.db.document_set import fetch_document_sets_for_document
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.relationships import delete_document_references_from_kg
from onyx.db.relationships import delete_documents_references_from_kg
from onyx.db.search_settings import get_active_search_settings
from onyx.document_index.factory import get_all_document_indices
from onyx.document_index.interfaces_new import MetadataUpdateRequest
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
    tenant_id: str,  # noqa: ARG001 — kept on the celery task signature
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

            active_search_settings = get_active_search_settings(db_session)
            # This flow is for updates and deletion so we get all indices.
            document_indices = get_all_document_indices(
                active_search_settings.primary,
                active_search_settings.secondary,
                httpx_client=HttpxPool.get("vespa"),
            )

            retry_document_indices: list[RetryDocumentIndex] = [
                RetryDocumentIndex(document_index)
                for document_index in document_indices
            ]

            count = get_document_connector_count(db_session, document_id)
            if count == 1:
                # count == 1 means this is the only remaining cc_pair reference to the doc
                # delete it from vespa and the db
                action = "delete"

                chunk_count = fetch_chunk_count_for_document(document_id, db_session)

                for retry_document_index in retry_document_indices:
                    _ = retry_document_index.delete(
                        document_id,
                        chunk_count=chunk_count,
                    )

                delete_document_references_from_kg(
                    db_session=db_session,
                    document_id=document_id,
                )

                delete_documents_complete(
                    db_session=db_session,
                    document_ids=[document_id],
                )

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

                update_request = MetadataUpdateRequest(
                    document_ids=[document_id],
                    doc_id_to_chunk_cnt={
                        document_id: (
                            doc.chunk_count if doc.chunk_count is not None else -1
                        )
                    },
                    access=doc_access,
                    document_sets=update_doc_sets,
                    boost=doc.boost,
                    hidden=doc.hidden,
                )

                for retry_document_index in retry_document_indices:
                    # TODO(andrei): Previously there was a comment here saying
                    # it was ok if a doc did not exist in the document index. I
                    # don't agree with that claim, so keep an eye on this task
                    # to see if this raises.
                    retry_document_index.update([update_request])

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
                f"doc={document_id} action={action} refcount={count} elapsed={elapsed:.2f}"
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
                        f"Non-retryable HTTPStatusError: doc={document_id} status={e.response.status_code}"
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
                    f"Max celery task retries reached. Marking doc as dirty for reconciliation: doc={document_id}"
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
                    db_session.commit()
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


def _reconcile_batch_for_retry(
    document_ids: list[str],
    cc_pair_identifier: ConnectorCredentialPairIdentifier,
) -> None:
    """Mark a whole batch as needing reconciliation.

    Used when the task hits max retries or SoftTimeLimitExceeded: drop the
    cc_pair link for every doc in the batch and stamp last_modified so the
    out-of-band stale-doc reconciler will eventually catch up. Mirrors the
    singular task's max-retries hook, just bulk-applied.
    """
    if not document_ids:
        return
    with get_session_with_current_tenant() as db_session:
        delete_documents_by_connector_credential_pair__no_commit(
            db_session=db_session,
            document_ids=document_ids,
            connector_credential_pair_identifier=cc_pair_identifier,
        )
        mark_documents_as_modified(document_ids, db_session)
        db_session.commit()


@shared_task(
    name=OnyxCeleryTask.DOCUMENT_BY_CC_PAIR_BULK_CLEANUP_TASK,
    soft_time_limit=LIGHT_SOFT_TIME_LIMIT,
    time_limit=LIGHT_TIME_LIMIT,
    max_retries=DOCUMENT_BY_CC_PAIR_CLEANUP_MAX_RETRIES,
    bind=True,
)
def document_by_cc_pair_bulk_cleanup_task(
    self: Task,
    document_ids: list[str],
    connector_id: int,
    credential_id: int,
    tenant_id: str,  # noqa: ARG001 — kept on the celery task signature
) -> bool:
    """Bulk variant of document_by_cc_pair_cleanup_task.

    Processes a whole batch of documents in three phases so the worker only
    holds a pgbouncer slot during Phase 1 and Phase 3, not across the
    document-index HTTP round-trip in Phase 2. Each batch becomes one Celery
    task ID, so the taskset shrinks from N entries to ceil(N / batch_size).

    Phase 1 (one DB session): bulk-bucket docs into delete / update / skip
        based on get_document_connector_counts. For the delete bucket, fetch
        chunk counts up front. For the update bucket, build per-doc
        MetadataUpdateRequests (per-doc reads — no bulk variant today and not
        on the hot path).
    Phase 2 (no DB session): one delete_batch call per document-index pair
        for the delete bucket; one update call per document-index pair for
        the update bucket (interface is already plural).
    Phase 3 (fresh DB session): bulk KG cascade + bulk delete_documents_complete
        for the delete bucket; bulk cc_pair detach + bulk mark_documents_as_synced
        for the update bucket.

    On exception or SoftTimeLimitExceeded, the whole batch is reconciled (one
    bulk cc_pair detach + bulk mark_documents_as_modified) so the stale-doc
    reconciler can pick up partial state. Retry countdown uses full jitter
    (random.uniform(0, 2^(retries+4))) to avoid thundering-herd on big
    failure waves.
    """
    if not document_ids:
        return True

    task_logger.debug(f"Bulk task start: n={len(document_ids)}")

    start = time.monotonic()
    completion_status = OnyxCeleryTaskCompletionStatus.UNDEFINED
    cc_pair_identifier = ConnectorCredentialPairIdentifier(
        connector_id=connector_id,
        credential_id=credential_id,
    )

    try:
        # Phase 1: read DB state and bucket. Release the session before any
        # document-index I/O.
        with get_session_with_current_tenant() as db_session:
            active_search_settings = get_active_search_settings(db_session)
            document_indices = get_all_document_indices(
                active_search_settings.primary,
                active_search_settings.secondary,
                httpx_client=HttpxPool.get("vespa"),
            )
            retry_document_indices: list[RetryDocumentIndex] = [
                RetryDocumentIndex(document_index)
                for document_index in document_indices
            ]

            # get_document_connector_counts only returns rows with count >= 1;
            # docs missing from the result are implicitly count == 0 and skip.
            counts: dict[str, int] = dict(
                get_document_connector_counts(db_session, document_ids)
            )

            delete_ids: list[str] = [
                doc_id for doc_id in document_ids if counts.get(doc_id) == 1
            ]
            update_ids: list[str] = [
                doc_id for doc_id in document_ids if counts.get(doc_id, 0) > 1
            ]

            delete_doc_id_to_chunk_count: dict[str, int | None] = {}
            if delete_ids:
                # fetch_chunk_counts_for_documents returns 0 for unknown rows.
                # That's fine for OpenSearch (uses doc IDs); Vespa's legacy
                # path will short-circuit a 0 chunk count to a no-op.
                chunk_count_pairs = fetch_chunk_counts_for_documents(
                    delete_ids, db_session
                )
                delete_doc_id_to_chunk_count = {
                    doc_id: chunk_count for doc_id, chunk_count in chunk_count_pairs
                }

            # Build one MetadataUpdateRequest per doc in the update bucket.
            # These reads don't have plural variants and aren't the hot path
            # (pruning hammers the delete path, not the update path).
            update_requests: list[MetadataUpdateRequest] = []
            for doc_id in update_ids:
                doc = get_document(doc_id, db_session)
                if not doc:
                    # Doc row vanished between Phase 1 bucketing and here.
                    # Silently drop from the update bucket; the cc_pair link
                    # will be cleaned up by reconciliation if it still exists.
                    continue
                doc_access = get_access_for_document(
                    document_id=doc_id, db_session=db_session
                )
                doc_sets = fetch_document_sets_for_document(doc_id, db_session)
                update_requests.append(
                    MetadataUpdateRequest(
                        document_ids=[doc_id],
                        doc_id_to_chunk_cnt={
                            doc_id: (
                                doc.chunk_count if doc.chunk_count is not None else -1
                            )
                        },
                        access=doc_access,
                        document_sets=set(doc_sets),
                        boost=doc.boost,
                        hidden=doc.hidden,
                    )
                )

            # Track which update docs we actually built requests for so
            # Phase 3 only touches those rows.
            update_ids_built: list[str] = [
                update_request.document_ids[0] for update_request in update_requests
            ]

        # Phase 2: document-index I/O. No DB session held.
        if delete_doc_id_to_chunk_count:
            for retry_document_index in retry_document_indices:
                retry_document_index.delete_batch(delete_doc_id_to_chunk_count)

        if update_requests:
            for retry_document_index in retry_document_indices:
                retry_document_index.update(update_requests)

        # Phase 3: write back in a fresh transaction.
        with get_session_with_current_tenant() as db_session:
            if delete_ids:
                # KG cascade stages writes; delete_documents_complete commits
                # everything in the session (KG + doc rows + cc_pair rows).
                delete_documents_references_from_kg(db_session, delete_ids)
                delete_documents_complete(
                    db_session=db_session,
                    document_ids=delete_ids,
                )

            if update_ids_built:
                # cc_pair detach stages; mark_documents_as_synced commits
                # both the detach and the sync timestamp.
                delete_documents_by_connector_credential_pair__no_commit(
                    db_session=db_session,
                    document_ids=update_ids_built,
                    connector_credential_pair_identifier=cc_pair_identifier,
                )
                mark_documents_as_synced(update_ids_built, db_session)

        completion_status = OnyxCeleryTaskCompletionStatus.SUCCEEDED

        elapsed = time.monotonic() - start
        # Use update_ids (bucketed) not update_ids_built (request built) so
        # the skip count reflects what bucketing actually saw. Docs that
        # bucketed as update but had a vanished row are tracked separately
        # as "dropped" — they aren't truly skipped (count > 1 at bucket time)
        # nor truly updated (no Phase 3 write).
        dropped = len(update_ids) - len(update_ids_built)
        skip = len(document_ids) - len(delete_ids) - len(update_ids)
        task_logger.info(
            "document_by_cc_pair_bulk_cleanup_task progress: "
            f"n={len(document_ids)} delete={len(delete_ids)} "
            f"update={len(update_ids_built)} dropped={dropped} "
            f"skip={skip} elapsed={elapsed:.2f}"
        )
    except SoftTimeLimitExceeded:
        # Bundled fix: previously the singular task silently dropped on
        # SoftTimeLimit. Reconcile the whole batch so the stale-doc reconciler
        # picks it up.
        task_logger.info(
            f"SoftTimeLimitExceeded for bulk cleanup batch. n={len(document_ids)}"
        )
        completion_status = OnyxCeleryTaskCompletionStatus.SOFT_TIME_LIMIT
        _reconcile_batch_for_retry(document_ids, cc_pair_identifier)
    except Exception as ex:
        e: Exception | None = None
        while True:
            if isinstance(ex, RetryError):
                task_logger.warning(
                    f"Tenacity retry failed: num_attempts={ex.last_attempt.attempt_number}"
                )
                e_temp = ex.last_attempt.exception()
                if isinstance(e_temp, Exception):
                    e = e_temp
            else:
                e = ex

            if isinstance(e, httpx.HTTPStatusError):
                if e.response.status_code == HTTPStatus.BAD_REQUEST:
                    task_logger.exception(
                        "Non-retryable HTTPStatusError on bulk batch. "
                        f"n={len(document_ids)} status={e.response.status_code}"
                    )
                completion_status = (
                    OnyxCeleryTaskCompletionStatus.NON_RETRYABLE_EXCEPTION
                )
                # Non-retryable: reconcile so docs aren't orphaned.
                _reconcile_batch_for_retry(document_ids, cc_pair_identifier)
                break

            task_logger.exception(
                "document_by_cc_pair_bulk_cleanup_task exceptioned. "
                f"n={len(document_ids)}"
            )

            completion_status = OnyxCeleryTaskCompletionStatus.RETRYABLE_EXCEPTION
            if (
                self.max_retries is not None
                and self.request.retries >= self.max_retries
            ):
                task_logger.warning(
                    "Max celery retries reached on bulk batch. Marking all "
                    f"docs dirty for reconciliation. n={len(document_ids)}"
                )
                _reconcile_batch_for_retry(document_ids, cc_pair_identifier)
                completion_status = (
                    OnyxCeleryTaskCompletionStatus.NON_RETRYABLE_EXCEPTION
                )
                break

            # Bundled fix: full jitter on retry countdown. Singular task uses
            # `2 ** (retries+4)` which is deterministic — N simultaneous
            # failures retry in lock-step. Use random.uniform(0, max) for
            # the same shape as wait_random_exponential in RetryDocumentIndex.
            max_countdown = 2 ** (self.request.retries + 4)
            countdown = random.uniform(0, max_countdown)
            self.retry(exc=e, countdown=countdown)
            break
    finally:
        task_logger.info(
            "document_by_cc_pair_bulk_cleanup_task completed: "
            f"status={completion_status.value} n={len(document_ids)}"
        )

    return completion_status == OnyxCeleryTaskCompletionStatus.SUCCEEDED


@shared_task(name=OnyxCeleryTask.CELERY_BEAT_HEARTBEAT, ignore_result=True, bind=True)
def celery_beat_heartbeat(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    """When this task runs, it writes a key to Redis with a TTL.

    An external observer can check this key to figure out if the celery beat is still running.
    """
    time_start = time.monotonic()
    r = get_redis_client()
    r.set(ONYX_CELERY_BEAT_HEARTBEAT_KEY, 1, ex=600)
    time_elapsed = time.monotonic() - time_start
    task_logger.info(f"celery_beat_heartbeat finished: elapsed={time_elapsed:.2f}")
