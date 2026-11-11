import time
from enum import Enum

from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from onyx.access.access import get_access_for_documents, get_null_document_access
from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.shared.models import CleanupBatchPlan
from onyx.configs.constants import ONYX_CELERY_BEAT_HEARTBEAT_KEY, OnyxCeleryTask
from onyx.db.connector_credential_pair import get_connector_credential_pair
from onyx.db.document import (
    delete_documents_by_connector_credential_pair__no_commit,
    delete_documents_complete,
    filter_existing_document_ids,
    get_cc_pair_ids_for_documents,
    get_document_connector_counts,
    get_document_ids_linked_to_other_cc_pairs,
    get_document_source_types,
    get_documents_for_update,
    mark_documents_as_modified__no_commit,
    mark_documents_as_synced__no_commit,
)
from onyx.db.document_set import fetch_document_sets_for_documents
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Document as DbDocument
from onyx.db.port_orphan_candidate import (
    clear_port_orphan_candidates,
    port_target_settings_id,
    record_port_orphan_candidates_for_documents,
)
from onyx.db.search_settings import ActiveSearchSettings, get_active_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import MetadataUpdateRequest
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import get_redis_client
from onyx.server.documents.models import ConnectorCredentialPairIdentifier

DOCUMENT_BY_CC_PAIR_CLEANUP_MAX_RETRIES = 3


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


def _clear_port_orphan_candidates_for_live_docs(
    db_session: Session,
    connector_id: int,
    credential_id: int,
    document_ids: list[str],
) -> None:
    """Drop the port orphan-candidates of docs a delete leaves LIVE, so a later port sweep
    doesn't delete the live docs' port-copied chunks. Scoped to (target, this cc_pair, docs)
    and idempotent, so it's safe across Celery retries. NOT for the transient-retry path: a
    candidate must survive an in-flight delete to still catch a mid-delete resurrection."""
    active_search_settings = get_active_search_settings(db_session)
    target_settings_id = port_target_settings_id(
        active_search_settings.primary, active_search_settings.secondary
    )
    if target_settings_id is None:
        return
    # Keep the candidate of a doc that lost its last link (being deleted): its port-copied
    # chunks remain (the index delete failed), so the sweep still needs to clean them.
    live_ids = [
        document_id
        for document_id, count in get_document_connector_counts(
            db_session, document_ids
        )
        if count
    ]
    if not live_ids:
        return
    cc_pair = get_connector_credential_pair(db_session, connector_id, credential_id)
    if cc_pair is None:
        return  # cc_pair deleted -> its FK cascade already dropped the candidates
    clear_port_orphan_candidates(db_session, target_settings_id, cc_pair.id, live_ids)


def _build_update_requests(
    db_session: Session, docs: list[DbDocument]
) -> list[MetadataUpdateRequest]:
    """Index metadata for docs whose links were just changed in this transaction."""
    document_ids = [doc.id for doc in docs]
    access_by_id = get_access_for_documents(document_ids, db_session)
    doc_sets_by_id = dict(fetch_document_sets_for_documents(document_ids, db_session))
    source_types_by_id = get_document_source_types(db_session, document_ids)
    cc_pair_ids_by_id = get_cc_pair_ids_for_documents(db_session, document_ids)

    update_requests: list[MetadataUpdateRequest] = []
    for doc in docs:
        source_types = source_types_by_id.get(doc.id)
        if not source_types:
            raise RuntimeError(
                f"Document {doc.id} has no source after relationship cleanup"
            )
        update_requests.append(
            MetadataUpdateRequest(
                document_ids=[doc.id],
                doc_id_to_chunk_cnt={
                    doc.id: doc.chunk_count if doc.chunk_count is not None else -1
                },
                access=access_by_id.get(doc.id) or get_null_document_access(),
                cc_pair_ids=set(cc_pair_ids_by_id.get(doc.id, [])),
                document_sets=set(doc_sets_by_id.get(doc.id, [])),
                boost=doc.boost,
                hidden=doc.hidden,
                source_types=source_types,
            )
        )
    return update_requests


def _plan_cleanup_batch(
    db_session: Session,
    active_search_settings: ActiveSearchSettings,
    document_ids: list[str],
    connector_id: int,
    credential_id: int,
) -> CleanupBatchPlan:
    """Phase 1: lock the batch, unlink the shared docs from this cc_pair and record
    port candidates for the docs about to be deleted, in one commit. The commit
    lands before any index write, so a failed or concurrent write retries safely
    off the stale watermark."""
    docs = get_documents_for_update(document_ids, db_session)
    if not docs:
        return CleanupBatchPlan(num_skipped=len(document_ids))

    existing_ids = [doc.id for doc in docs]
    linked_ids = {
        document_id
        for document_id, count in get_document_connector_counts(
            db_session, existing_ids
        )
        if count
    }
    shared_ids = get_document_ids_linked_to_other_cc_pairs(
        db_session, existing_ids, connector_id, credential_id
    )
    plan = CleanupBatchPlan(
        # A doc with no links at all needs nothing from this cc_pair.
        delete_ids=[
            doc_id
            for doc_id in existing_ids
            if doc_id in linked_ids and doc_id not in shared_ids
        ],
        update_ids=[doc_id for doc_id in existing_ids if doc_id in shared_ids],
    )
    plan.num_skipped = len(document_ids) - len(plan.delete_ids) - len(plan.update_ids)

    if plan.update_ids:
        delete_documents_by_connector_credential_pair__no_commit(
            db_session=db_session,
            document_ids=plan.update_ids,
            connector_credential_pair_identifier=ConnectorCredentialPairIdentifier(
                connector_id=connector_id,
                credential_id=credential_id,
            ),
        )
        plan.update_modified_at = mark_documents_as_modified__no_commit(
            plan.update_ids, db_session
        )
        update_ids = set(plan.update_ids)
        plan.update_requests = _build_update_requests(
            db_session, [doc for doc in docs if doc.id in update_ids]
        )

    if plan.delete_ids:
        # If a port is filling a target index, record these deletes so the cc_pair's
        # port attempt sweeps a doc back out if a racing create-only copy resurrects
        # it. The commit below makes the candidates durable before the index delete.
        record_port_orphan_candidates_for_documents(
            db_session,
            plan.delete_ids,
            active_search_settings.primary,
            active_search_settings.secondary,
        )

    db_session.commit()
    return plan


def _hand_batch_to_reconciliation(
    document_ids: list[str],
    connector_id: int,
    credential_id: int,
    tenant_id: str,
    prune_cc_pair_id: int | None,
) -> None:
    """Last-retry fallback: unlink every remaining doc from this cc_pair and mark it
    modified, so stale-document reconciliation repairs the index out of band."""
    task_logger.warning(
        "Max celery task retries reached. Marking docs as dirty for reconciliation: "
        f"docs={len(document_ids)} first_doc={document_ids[0]}"
    )
    with get_session_with_current_tenant() as db_session:
        failed_ids = list(filter_existing_document_ids(db_session, document_ids))
        delete_documents_by_connector_credential_pair__no_commit(
            db_session=db_session,
            document_ids=failed_ids,
            connector_credential_pair_identifier=ConnectorCredentialPairIdentifier(
                connector_id=connector_id,
                credential_id=credential_id,
            ),
        )
        mark_documents_as_modified__no_commit(failed_ids, db_session)
        # helper keeps the candidate of a doc this removed the last link from
        _clear_port_orphan_candidates_for_live_docs(
            db_session, connector_id, credential_id, failed_ids
        )
        db_session.commit()

    if prune_cc_pair_id is None or not failed_ids:
        return
    # The count is advisory, so a Redis failure must not change the outcome.
    try:
        RedisConnector(tenant_id, prune_cc_pair_id).prune.increment_failed_docs(
            len(failed_ids)
        )
    except Exception:
        task_logger.exception(
            f"Could not count the failed prune docs: cc_pair={prune_cc_pair_id} "
            f"docs={len(failed_ids)}"
        )


def _cleanup_documents(
    task: Task,
    document_ids: list[str],
    connector_id: int,
    credential_id: int,
    tenant_id: str,
    prune_cc_pair_id: int | None,
) -> bool:
    """Remove a batch of documents' links to one cc_pair and reconcile the index.

    Each step runs once for the whole batch. The DB session is released before
    the document-index calls: holding a pg transaction across the round-trip pins
    a pgbouncer slot and saturates the pool under bulk-deletion fan-out.
    """
    start = time.monotonic()
    completion_status = OnyxCeleryTaskCompletionStatus.UNDEFINED
    first_doc = document_ids[0]

    try:
        with get_session_with_current_tenant() as db_session:
            active_search_settings = get_active_search_settings(db_session)
            plan = _plan_cleanup_batch(
                db_session,
                active_search_settings,
                document_ids,
                connector_id,
                credential_id,
            )

        if not plan.delete_ids and not plan.update_ids:
            completion_status = OnyxCeleryTaskCompletionStatus.SKIPPED
            return False

        # Client construction can take seconds, so it also stays outside the session.
        document_index = get_default_document_index(
            active_search_settings.primary,
            active_search_settings.secondary,
        )

        # Phase 2: document-index I/O — no DB connection held.
        if plan.delete_ids:
            document_index.delete_documents(plan.delete_ids)
        if plan.update_requests:
            document_index.update(plan.update_requests)

        # Phase 3: write back to PG in fresh transactions.
        if plan.delete_ids:
            with get_session_with_current_tenant() as db_session:
                delete_documents_complete(
                    db_session=db_session,
                    document_ids=plan.delete_ids,
                )
        if plan.update_ids:
            if plan.update_modified_at is None:
                raise RuntimeError("Updated docs were planned without a watermark")
            with get_session_with_current_tenant() as db_session:
                # The phase-1 watermark keeps a concurrently-modified doc stale.
                mark_documents_as_synced__no_commit(
                    plan.update_ids, db_session, synced_as_of=plan.update_modified_at
                )
                # re-link -> docs stay live under another cc_pair; drop stale candidates
                _clear_port_orphan_candidates_for_live_docs(
                    db_session, connector_id, credential_id, plan.update_ids
                )
                db_session.commit()

        completion_status = OnyxCeleryTaskCompletionStatus.SUCCEEDED
        task_logger.info(
            f"Document cleanup batch: first_doc={first_doc} "
            f"deleted={len(plan.delete_ids)} updated={len(plan.update_ids)} "
            f"skipped={plan.num_skipped} elapsed={time.monotonic() - start:.2f}"
        )
    except SoftTimeLimitExceeded:
        task_logger.info(f"SoftTimeLimitExceeded exception. first_doc={first_doc}")
        completion_status = OnyxCeleryTaskCompletionStatus.SOFT_TIME_LIMIT
    except Exception as e:
        task_logger.exception(
            f"Document cleanup batch exceptioned: first_doc={first_doc} "
            f"docs={len(document_ids)}"
        )

        completion_status = OnyxCeleryTaskCompletionStatus.RETRYABLE_EXCEPTION
        if task.max_retries is not None and task.request.retries >= task.max_retries:
            _hand_batch_to_reconciliation(
                document_ids, connector_id, credential_id, tenant_id, prune_cc_pair_id
            )
            completion_status = OnyxCeleryTaskCompletionStatus.NON_RETRYABLE_EXCEPTION
        else:
            # Exponential backoff from 2^4 to 2^6 ... i.e. 16, 32, 64
            countdown = 2 ** (task.request.retries + 4)
            task.retry(exc=e, countdown=countdown)  # this will raise a celery exception
    finally:
        task_logger.info(
            f"Document cleanup batch completed: status={completion_status.value} "
            f"first_doc={first_doc} docs={len(document_ids)}"
        )

    return completion_status == OnyxCeleryTaskCompletionStatus.SUCCEEDED


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.DOCUMENT_BATCH_BY_CC_PAIR_CLEANUP_TASK,
    soft_time_limit=LIGHT_SOFT_TIME_LIMIT,
    time_limit=LIGHT_TIME_LIMIT,
    max_retries=DOCUMENT_BY_CC_PAIR_CLEANUP_MAX_RETRIES,
    bind=True,
)
def document_batch_by_cc_pair_cleanup_task(
    self: Task,
    document_ids: list[str],
    connector_id: int,
    credential_id: int,
    tenant_id: str,
    prune_cc_pair_id: int | None = None,
) -> bool:
    """Remove a batch of documents' links to one cc_pair (connector deletion or
    pruning). Docs left without links are deleted; the rest are re-synced."""
    return _cleanup_documents(
        self, document_ids, connector_id, credential_id, tenant_id, prune_cc_pair_id
    )


# TODO(evan-onyx): delete one release after document_batch_by_cc_pair_cleanup_task
# ships; it only drains messages queued before the upgrade.
@shared_task(  # ty: ignore[invalid-argument-type]
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
    prune_cc_pair_id: int | None = None,
) -> bool:
    return _cleanup_documents(
        self, [document_id], connector_id, credential_id, tenant_id, prune_cc_pair_id
    )


@shared_task(name=OnyxCeleryTask.CELERY_BEAT_HEARTBEAT, ignore_result=True, bind=True)  # ty: ignore[invalid-argument-type]
def celery_beat_heartbeat(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    """When this task runs, it writes a key to Redis with a TTL.

    An external observer can check this key to figure out if the celery beat is still running.
    """
    time_start = time.monotonic()
    r = get_redis_client()
    r.set(ONYX_CELERY_BEAT_HEARTBEAT_KEY, 1, ex=600)
    time_elapsed = time.monotonic() - time_start
    task_logger.info(f"celery_beat_heartbeat finished: elapsed={time_elapsed:.2f}")
