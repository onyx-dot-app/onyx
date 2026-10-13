import time
import traceback
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import NamedTuple
from uuid import uuid4

from celery import Celery, Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from redis.lock import Lock as RedisLock
from sqlalchemy.exc import NoResultFound
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_delay,
    wait_random_exponential,
)

from ee.onyx.db.connector_credential_pair import (
    clear_perm_sync_pending__no_commit,
    get_all_auto_sync_cc_pairs,
    get_perm_sync_pending_cc_pair_sources,
)
from ee.onyx.db.document import upsert_document_external_perms
from ee.onyx.external_permissions.sync_params import get_source_perm_sync_config
from onyx.access.models import DocExternalAccess, ElementExternalAccess
from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.tasks.shared.lease_heartbeat import LeaseHeartbeat
from onyx.configs.app_configs import JOB_TIMEOUT, PERMISSION_SYNC_TIMEOUT
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    PERMISSION_SYNC_HEARTBEAT_INTERVAL,
    PERMISSION_SYNC_LEASE_OVERRUN,
    PERMISSION_SYNC_LEASE_SELF_EXPIRY,
    PERMISSION_SYNC_LEASE_TIMEOUT,
    PERMISSION_SYNC_TASK_EXPIRES,
    DocumentSource,
    OnyxCeleryPriority,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.connectors.factory import validate_ccpair_for_user
from onyx.db.connector import mark_cc_pair_as_permissions_synced
from onyx.db.connector_credential_pair import get_connector_credential_pair_from_id
from onyx.db.document import (
    get_document_ids_for_connector_credential_pair,
    get_documents_for_connector_credential_pair_limited_columns,
    upsert_document_by_connector_credential_pair,
)
from onyx.db.engine.sql_engine import (
    get_session_with_current_tenant,
    get_session_with_tenant,
)
from onyx.db.enums import (
    CapabilityCheckTrigger,
    ConnectorCredentialPairStatus,
)
from onyx.db.hierarchy import (
    update_hierarchy_node_permissions as db_update_hierarchy_node_permissions,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.db.permission_sync_attempt import (
    DocPermissionSyncProgress,
    complete_doc_permission_sync_attempt,
    fail_expired_doc_permission_sync_attempts,
    get_cc_pair_ids_with_open_doc_permission_sync_attempt,
    mark_doc_permission_sync_attempt_failed,
    mark_doc_permission_sync_attempt_in_progress,
    renew_doc_permission_sync_attempt_lease,
    try_create_doc_permission_sync_attempt,
)
from onyx.db.users import batch_add_ext_perm_user_if_not_exists
from onyx.db.utils import DocumentRow, SortOrder, is_retryable_sqlalchemy_error
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_pool import (
    get_redis_client,
)
from onyx.redis.redis_tenant_work_gating import maybe_mark_tenant_active
from onyx.server.metrics.perm_sync_metrics import (
    inc_doc_perm_sync_docs_processed,
    inc_doc_perm_sync_errors,
    observe_doc_perm_sync_db_update_duration,
    observe_doc_perm_sync_duration,
)
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from onyx.utils.logger import (
    LoggerContextVars,
    doc_permission_sync_ctx,
    format_error_for_logging,
    setup_logger,
)

logger = setup_logger()


DOCUMENT_PERMISSIONS_UPDATE_MAX_RETRIES = 3
DOCUMENT_PERMISSIONS_UPDATE_STOP_AFTER = 10 * 60
DOCUMENT_PERMISSIONS_UPDATE_MAX_WAIT = 60


DOC_PERMISSION_SYNC_TASK_ID_PREFIX = "docpermissionsync"

LIGHT_SOFT_TIME_LIMIT = 105
LIGHT_TIME_LIMIT = LIGHT_SOFT_TIME_LIMIT + 15


"""Jobs / utils for kicking off doc permissions sync tasks."""


def _fail_doc_permission_sync_attempt(
    attempt_id: int,
    error_msg: str,
    full_exception_trace: str | None = None,
    total_docs_synced: int = 0,
    docs_with_permission_errors: int = 0,
) -> None:
    """Helper to mark a doc permission sync attempt as failed with an error message."""
    with get_session_with_current_tenant() as db_session:
        mark_doc_permission_sync_attempt_failed(
            attempt_id,
            db_session,
            error_message=error_msg,
            full_exception_trace=full_exception_trace,
            total_docs_synced=total_docs_synced,
            docs_with_permission_errors=docs_with_permission_errors,
        )


def _renew_doc_permission_sync_lease(
    attempt_id: int, progress: DocPermissionSyncProgress
) -> bool:
    with get_session_with_current_tenant() as db_session:
        return renew_doc_permission_sync_attempt_lease(attempt_id, db_session, progress)


def fail_expired_doc_permission_sync_attempts_for_tenant() -> None:
    lease_timeout = timedelta(seconds=PERMISSION_SYNC_LEASE_TIMEOUT)
    with get_session_with_current_tenant() as db_session:
        failed_ids = fail_expired_doc_permission_sync_attempts(
            db_session,
            lease_timeout=lease_timeout,
            # Celery has dropped the task by then, so it can never start
            not_started_timeout=timedelta(seconds=PERMISSION_SYNC_TASK_EXPIRES)
            + lease_timeout,
        )
    if failed_ids:
        task_logger.warning(
            f"Failed doc permission sync attempts with expired leases: {failed_ids}"
        )


def _stop_reason_for_failure(callback: "PermissionSyncCallback | None") -> str | None:
    """The stop cause to record with a failure. It never raises (the stop signal
    lives in Redis), so the failure is always recorded."""
    if callback is None:
        return None
    try:
        return callback.stop_reason()
    except Exception:
        task_logger.exception("Could not read the permission sync stop reason")
        return None


def is_external_doc_permissions_sync_due(cc_pair: ConnectorCredentialPair) -> bool:
    """Returns boolean indicating if external doc permissions sync is due."""

    if not cc_pair.access_type.is_perm_synced():
        return False

    # skip doc permissions sync if not active
    if cc_pair.status != ConnectorCredentialPairStatus.ACTIVE:
        return False

    sync_config = get_source_perm_sync_config(cc_pair.connector.source)
    if sync_config is None:
        logger.error("No sync config found for %s", cc_pair.connector.source)
        return False

    if sync_config.doc_sync_config is None:
        logger.error("No doc sync config found for %s", cc_pair.connector.source)
        return False

    # if indexing also does perm sync, don't start running doc_sync until at
    # least one indexing is done
    if (
        sync_config.doc_sync_config.initial_index_should_sync
        and cc_pair.last_successful_index_time is None
    ):
        return False

    # If the last sync is None, it has never been run so we run the sync
    last_perm_sync = cc_pair.last_time_perm_sync
    if last_perm_sync is None:
        return True

    # A sync that started before the pair began to wait for its first
    # permission sync does not count, so the pair is not hidden for a period.
    pending_since = cc_pair.perm_sync_pending_since
    if pending_since is not None and last_perm_sync < pending_since:
        return True

    source_sync_period = sync_config.doc_sync_config.doc_sync_frequency
    source_sync_period *= int(OnyxRuntime.get_doc_permission_sync_multiplier())

    # If the last sync is greater than the full fetch period, we run the sync
    next_sync = last_perm_sync + timedelta(seconds=source_sync_period)
    if datetime.now(timezone.utc) >= next_sync:
        return True

    return False


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CHECK_FOR_DOC_PERMISSIONS_SYNC,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
    bind=True,
)
def check_for_doc_permissions_sync(self: Task, *, tenant_id: str) -> bool | None:
    r = get_redis_client()

    lock_beat: RedisLock = r.lock(
        OnyxRedisLocks.CHECK_CONNECTOR_DOC_PERMISSIONS_SYNC_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    try:
        # Fail abandoned attempts first, so their cc_pairs can be dispatched again
        fail_expired_doc_permission_sync_attempts_for_tenant()

        # get all cc pairs that need to be synced
        cc_pair_ids_to_sync: list[int] = []
        with get_session_with_current_tenant() as db_session:
            cc_pairs = get_all_auto_sync_cc_pairs(db_session)
            running_cc_pair_ids = get_cc_pair_ids_with_open_doc_permission_sync_attempt(
                db_session
            )

            cc_pair_ids_to_sync.extend(
                cc_pair.id
                for cc_pair in cc_pairs
                if cc_pair.id not in running_cc_pair_ids
                and is_external_doc_permissions_sync_due(cc_pair)
            )

        # Tenant-work-gating hook: refresh this tenant's active-set membership
        # whenever doc-permission sync has any due cc_pairs to dispatch.
        if cc_pair_ids_to_sync:
            maybe_mark_tenant_active(tenant_id, caller="doc_permission_sync")

        lock_beat.reacquire()
        for cc_pair_id in cc_pair_ids_to_sync:
            attempt_id = try_creating_permissions_sync_task(
                self.app, cc_pair_id, tenant_id
            )
            if attempt_id is None:
                continue

            task_logger.info(
                f"Permissions sync queued: cc_pair={cc_pair_id} attempt={attempt_id}"
            )

        lock_beat.reacquire()
        clear_caught_up_perm_sync_pending_marks(tenant_id)
        task_logger.info(f"check_for_doc_permissions_sync finished: tenant={tenant_id}")
    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
    except Exception as e:
        error_msg = format_error_for_logging(e)
        task_logger.warning(
            f"Unexpected check_for_doc_permissions_sync exception: tenant={tenant_id} {error_msg}"
        )
        task_logger.exception(
            f"Unexpected check_for_doc_permissions_sync exception: tenant={tenant_id}"
        )
    finally:
        if lock_beat.owned():
            lock_beat.release()

    return True


def clear_caught_up_perm_sync_pending_marks(tenant_id: str) -> None:
    """Clears the mark of each pair awaiting its first permission sync whose
    permissions are now in the document index. Group ACL entries are only as
    current as the group memberships, so a source with group sync also waits
    for one. A mark on a source with no doc permission sync clears at once."""
    with get_session_with_current_tenant() as db_session:
        pending_cc_pair_sources = get_perm_sync_pending_cc_pair_sources(db_session)
        if not pending_cc_pair_sources:
            return
        # Keeps this beat running for the tenant until the marks clear.
        maybe_mark_tenant_active(tenant_id, caller="doc_permission_sync")
        for cc_pair_id, source in pending_cc_pair_sources.items():
            sync_config = get_source_perm_sync_config(source)
            if clear_perm_sync_pending__no_commit(
                db_session,
                cc_pair_id,
                needs_doc_sync=(
                    sync_config is not None and sync_config.doc_sync_config is not None
                ),
                needs_group_sync=(
                    sync_config is not None
                    and sync_config.group_sync_config is not None
                ),
            ):
                task_logger.info(
                    f"Cleared perm sync pending mark: cc_pair={cc_pair_id}"
                )
        db_session.commit()


def try_creating_permissions_sync_task(
    app: Celery,
    cc_pair_id: int,
    tenant_id: str,
) -> int | None:
    """Creates a NOT_STARTED attempt and dispatches the task that runs it.
    Returns the attempt ID, or None when nothing was dispatched: the cc_pair
    already has an open attempt, or it is being deleted or pruned."""
    redis_connector = RedisConnector(tenant_id, cc_pair_id)
    if redis_connector.delete.fenced or redis_connector.prune.fenced:
        return None

    celery_task_id = f"{DOC_PERMISSION_SYNC_TASK_ID_PREFIX}_{cc_pair_id}_{uuid4()}"
    with get_session_with_current_tenant() as db_session:
        attempt_id = try_create_doc_permission_sync_attempt(
            cc_pair_id, celery_task_id, db_session
        )
    if attempt_id is None:
        return None

    try:
        app.send_task(
            OnyxCeleryTask.CONNECTOR_PERMISSION_SYNC_GENERATOR_TASK,
            kwargs={
                "cc_pair_id": cc_pair_id,
                "tenant_id": tenant_id,
                "attempt_id": attempt_id,
            },
            queue=OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC,
            task_id=celery_task_id,
            priority=OnyxCeleryPriority.MEDIUM,
            expires=PERMISSION_SYNC_TASK_EXPIRES,
        )
    except Exception as e:
        task_logger.exception(
            f"Failed to dispatch permission sync: cc_pair={cc_pair_id} attempt={attempt_id}"
        )
        _fail_doc_permission_sync_attempt(
            attempt_id,
            f"Failed to dispatch the permission sync task: {format_error_for_logging(e)}",
            full_exception_trace=traceback.format_exc(),
        )
        return None

    return attempt_id


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CONNECTOR_PERMISSION_SYNC_GENERATOR_TASK,
    acks_late=False,
    soft_time_limit=JOB_TIMEOUT,
    track_started=True,
    trail=False,
    bind=True,
)
def connector_permission_sync_generator_task(
    self: Task,
    cc_pair_id: int,
    tenant_id: str,
    attempt_id: int | None = None,
) -> None:
    """
    Permission sync task that handles document permission syncing for a given connector credential pair.
    The dispatcher created the NOT_STARTED attempt; this task owns it while its lease holds.
    """
    LoggerContextVars.reset()

    doc_permission_sync_ctx_dict = dict(doc_permission_sync_ctx.get())
    doc_permission_sync_ctx_dict["cc_pair_id"] = cc_pair_id
    doc_permission_sync_ctx_dict["request_id"] = self.request.id
    doc_permission_sync_ctx.set(doc_permission_sync_ctx_dict)

    if attempt_id is None:
        # Dispatched by a release that kept the sync lock in Redis
        task_logger.warning(
            f"Permission sync task has no attempt, skipping: cc_pair={cc_pair_id}"
        )
        return None

    sync_started_at = datetime.now(timezone.utc)
    with get_session_with_current_tenant() as db_session:
        try:
            mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)
        except (RuntimeError, NoResultFound):
            # The reaper or a cancel closed the attempt while the task was queued
            task_logger.warning(
                f"Permission sync attempt is no longer runnable, skipping: "
                f"cc_pair={cc_pair_id} attempt={attempt_id}"
            )
            return None

    redis_connector = RedisConnector(tenant_id, cc_pair_id)

    sync_start = time.monotonic()
    connector_type: str = "unknown"
    tasks_generated = 0
    docs_with_errors = 0
    progress = DocPermissionSyncProgress()
    heartbeat = LeaseHeartbeat(
        f"doc_permission_sync_attempt={attempt_id}",
        renew=partial(_renew_doc_permission_sync_lease, attempt_id, progress),
        interval=PERMISSION_SYNC_HEARTBEAT_INTERVAL,
        max_silence=PERMISSION_SYNC_LEASE_SELF_EXPIRY,
        max_duration=PERMISSION_SYNC_TIMEOUT + PERMISSION_SYNC_LEASE_OVERRUN,
    )
    heartbeat.start()
    callback = PermissionSyncCallback(
        redis_connector,
        timeout_seconds=PERMISSION_SYNC_TIMEOUT,
        lease=heartbeat,
        sync_progress=progress,
    )
    try:
        # Scoped to setup, never across the crawl below: on multi-tenant this session
        # is bound to one checked-out Connection, which PgBouncer closes once the gaps
        # between its queries pass client_idle_timeout.
        with get_session_with_current_tenant() as db_session:
            cc_pair = get_connector_credential_pair_from_id(
                db_session=db_session,
                cc_pair_id=cc_pair_id,
                eager_load_connector=True,
                eager_load_credential=True,
            )
            if cc_pair is None:
                raise ValueError(
                    f"No connector credential pair found for id: {cc_pair_id}"
                )

            if not cc_pair.access_type.is_perm_synced():
                error_msg = (
                    f"cc_pair={cc_pair_id} is not perm-synced: {cc_pair.access_type}"
                )
                task_logger.warning(error_msg)
                _fail_doc_permission_sync_attempt(attempt_id, error_msg)
                return None

            try:
                created = validate_ccpair_for_user(
                    cc_pair.connector.id,
                    cc_pair.credential.id,
                    cc_pair.access_type,
                    db_session,
                    enforce_creation=False,
                    trigger=CapabilityCheckTrigger.PERM_SYNC_ATTEMPT,
                    user=None,
                )
                if not created:
                    task_logger.warning(
                        f"Unable to create connector credential pair for id: {cc_pair_id}"
                    )
            except Exception:
                task_logger.exception(
                    f"validate_ccpair_permissions_sync exceptioned: cc_pair={cc_pair_id}"
                )
                # TODO: add some notification to the admins here
                raise

            source_type = cc_pair.connector.source
            connector_type = source_type.value
            sync_config = get_source_perm_sync_config(source_type)
            if sync_config is None:
                error_msg = f"No sync config found for {source_type}"
                logger.error(error_msg)
                _fail_doc_permission_sync_attempt(attempt_id, error_msg)
                return None

            if sync_config.doc_sync_config is None:
                if sync_config.censoring_config:
                    error_msg = f"Doc sync config is None but censoring config exists for {source_type}"
                    _fail_doc_permission_sync_attempt(attempt_id, error_msg)
                    return None

                raise ValueError(
                    f"No doc sync func found for {source_type} with cc_pair={cc_pair_id}"
                )

            logger.info("Syncing docs for %s with cc_pair=%s", source_type, cc_pair_id)

            connector_id = cc_pair.connector.id
            credential_id = cc_pair.credential.id

        # lets each connector decide which existing docs are now missing and should
        # lose access
        def fetch_all_existing_docs_fn(
            sort_order: SortOrder | None = None,
        ) -> list[DocumentRow]:
            with get_session_with_current_tenant() as fetch_session:
                return list(
                    get_documents_for_connector_credential_pair_limited_columns(
                        db_session=fetch_session,
                        connector_id=connector_id,
                        credential_id=credential_id,
                        sort_order=sort_order,
                    )
                )

        def fetch_all_existing_docs_ids_fn() -> list[str]:
            with get_session_with_current_tenant() as fetch_session:
                return get_document_ids_for_connector_credential_pair(
                    db_session=fetch_session,
                    connector_id=connector_id,
                    credential_id=credential_id,
                )

        # cc_pair is detached: connectors may read eager-loaded connector/credential
        # columns off it, never a lazy relationship.
        doc_sync_func = sync_config.doc_sync_config.doc_sync_func
        document_external_accesses = doc_sync_func(
            cc_pair,
            fetch_all_existing_docs_fn,
            fetch_all_existing_docs_ids_fn,
            callback,
        )

        task_logger.info(f"Permission sync crawl starting. cc_pair={cc_pair_id}")

        for doc_external_access in document_external_accesses:
            stop_reason = callback.stop_reason()
            if stop_reason is not None:
                raise RuntimeError(
                    f"Permission sync stopped: {stop_reason}: "
                    f"cc_pair={cc_pair_id} "
                    f"tasks_generated={tasks_generated}"
                )

            result = update_element_permissions_batch(
                tenant_id=tenant_id,
                new_permissions=[doc_external_access],
                source_string=connector_type,
                connector_id=connector_id,
                credential_id=credential_id,
            )
            tasks_generated += result.num_updated
            docs_with_errors += result.num_errors
            progress.total_docs_synced = tasks_generated
            progress.docs_with_permission_errors = docs_with_errors
            progress.last_progress_at = datetime.now(timezone.utc)

        task_logger.info(
            f"Permission sync crawl finished. "
            f"cc_pair={cc_pair_id} tasks_generated={tasks_generated} docs_with_errors={docs_with_errors}"
        )

        inc_doc_perm_sync_docs_processed(connector_type, tasks_generated)
        if docs_with_errors > 0:
            inc_doc_perm_sync_errors(connector_type, docs_with_errors)

        with get_session_with_current_tenant() as db_session:
            complete_doc_permission_sync_attempt(
                db_session=db_session,
                attempt_id=attempt_id,
                total_docs_synced=tasks_generated,
                docs_with_permission_errors=docs_with_errors,
            )
            mark_cc_pair_as_permissions_synced(db_session, cc_pair_id, sync_started_at)
        task_logger.info(
            f"Completed doc permission sync attempt {attempt_id}: {tasks_generated} docs, {docs_with_errors} errors"
        )

    except Exception as e:
        error_msg = format_error_for_logging(e)
        full_exception_trace = traceback.format_exc()
        # Connectors raise a generic "stop signal" error for every stop cause
        stop_reason = _stop_reason_for_failure(callback)
        if stop_reason is not None:
            error_msg = f"Permission sync stopped: {stop_reason}. {error_msg}"

        task_logger.warning(
            f"Permission sync exceptioned: cc_pair={cc_pair_id} attempt={attempt_id} {error_msg}"
        )
        task_logger.exception(
            f"Permission sync exceptioned: cc_pair={cc_pair_id} attempt={attempt_id}"
        )

        _fail_doc_permission_sync_attempt(
            attempt_id,
            error_msg,
            full_exception_trace=full_exception_trace,
            total_docs_synced=tasks_generated,
            docs_with_permission_errors=docs_with_errors,
        )
        raise e
    finally:
        heartbeat.stop()
        observe_doc_perm_sync_duration(time.monotonic() - sync_start, connector_type)

    task_logger.info(
        f"Permission sync finished: cc_pair={cc_pair_id} attempt={attempt_id}"
    )


class PermissionSyncResult(NamedTuple):
    """Result of a permission sync operation.

    Attributes:
        num_updated: Number of documents successfully updated
        num_errors: Number of documents that failed to update
    """

    num_updated: int
    num_errors: int


def update_element_permissions_batch(
    tenant_id: str,
    new_permissions: list[ElementExternalAccess],
    source_string: str,
    connector_id: int,
    credential_id: int,
) -> PermissionSyncResult:
    """Update permissions for documents and hierarchy nodes.

    Returns:
        PermissionSyncResult containing counts of successful updates and errors
    """
    num_permissions = 0
    num_errors = 0
    cumulative_db_update_time = 0.0
    for permissions in new_permissions:
        element_id = (
            permissions.doc_id
            if isinstance(permissions, DocExternalAccess)
            else permissions.raw_node_id
        )
        if (
            permissions.external_access.num_entries
            > permissions.external_access.MAX_NUM_ENTRIES
        ):
            num_errors += 1
            task_logger.warning(
                "Permissions length exceeded, skipping...: "
                "%s "
                "num_users=%s num_groups=%s "
                "permissions.external_access.MAX_NUM_ENTRIES=%s",
                element_id,
                len(permissions.external_access.external_user_emails),
                len(permissions.external_access.external_user_group_ids),
                permissions.external_access.MAX_NUM_ENTRIES,
            )
            continue

        # NOTE(rkuo): this used to fire a task instead of directly writing to the DB,
        # but the permissions can be excessively large if sent over the wire.
        # On the other hand, the downside of doing db updates here is that we can
        # block and fail if we can't make the calls to the DB ... but that's probably
        # a rare enough case to be acceptable.

        # This can internally exception due to db issues but still continue
        # Catch exceptions per-element to avoid breaking the entire sync
        db_start = time.monotonic()
        try:
            element_update_permissions(
                tenant_id,
                permissions,
                source_string,
                connector_id,
                credential_id,
            )
            num_permissions += 1
        except Exception:
            num_errors += 1
            task_logger.exception(
                "Failed to update permissions for element %s", element_id
            )
        finally:
            cumulative_db_update_time += time.monotonic() - db_start

    observe_doc_perm_sync_db_update_duration(cumulative_db_update_time, source_string)
    return PermissionSyncResult(num_updated=num_permissions, num_errors=num_errors)


# NOTE(rkuo): this should probably move to the db layer
@retry(
    retry=retry_if_exception(is_retryable_sqlalchemy_error),
    wait=wait_random_exponential(
        multiplier=1, max=DOCUMENT_PERMISSIONS_UPDATE_MAX_WAIT
    ),
    stop=stop_after_delay(DOCUMENT_PERMISSIONS_UPDATE_STOP_AFTER),
)
def element_update_permissions(
    tenant_id: str,
    permissions: ElementExternalAccess,
    source_type_str: str,
    connector_id: int,
    credential_id: int,
) -> bool:
    """Update permissions for a document or hierarchy node."""
    start = time.monotonic()
    external_access = permissions.external_access

    # Determine element type and identifier for logging
    if isinstance(permissions, DocExternalAccess):
        element_id = permissions.doc_id
        element_type = "doc"
    else:
        element_id = permissions.raw_node_id
        element_type = "node"

    try:
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            # Add the users to the DB if they don't exist
            batch_add_ext_perm_user_if_not_exists(
                db_session=db_session,
                emails=list(external_access.external_user_emails),
                continue_on_error=True,
            )

            if isinstance(permissions, DocExternalAccess):
                # Document permission update
                created_new_doc = upsert_document_external_perms(
                    db_session=db_session,
                    doc_id=permissions.doc_id,
                    external_access=external_access,
                    source_type=DocumentSource(source_type_str),
                )

                if created_new_doc:
                    # If a new document was created, we associate it with the cc_pair
                    upsert_document_by_connector_credential_pair(
                        db_session=db_session,
                        connector_id=connector_id,
                        credential_id=credential_id,
                        document_ids=[permissions.doc_id],
                    )
            else:
                # Hierarchy node permission update
                db_update_hierarchy_node_permissions(
                    db_session=db_session,
                    raw_node_id=permissions.raw_node_id,
                    source=DocumentSource(permissions.source),
                    is_public=external_access.is_public,
                    external_user_emails=(
                        list(external_access.external_user_emails)
                        if external_access.external_user_emails
                        else None
                    ),
                    external_user_group_ids=(
                        list(external_access.external_user_group_ids)
                        if external_access.external_user_group_ids
                        else None
                    ),
                )

            elapsed = time.monotonic() - start
            task_logger.info(
                f"{element_type}={element_id} action=update_permissions elapsed={elapsed:.2f}"
            )
    except Exception as e:
        task_logger.exception(
            f"element_update_permissions exceptioned: {element_type}={element_id}, {connector_id=} {credential_id=}"
        )
        raise e
    finally:
        task_logger.info(
            f"element_update_permissions completed: {element_type}={element_id}, {connector_id=} {credential_id=}"
        )

    return True


class PermissionSyncCallback(IndexingHeartbeatInterface):
    def __init__(
        self,
        redis_connector: RedisConnector,
        timeout_seconds: int | None = None,
        lease: LeaseHeartbeat | None = None,
        sync_progress: DocPermissionSyncProgress | None = None,
    ):
        super().__init__()
        self.redis_connector: RedisConnector = redis_connector
        self.start_monotonic = time.monotonic()
        self.timeout_seconds = timeout_seconds
        self.lease = lease
        self.sync_progress = sync_progress

    def stop_reason(self) -> str | None:
        """Why the sync must stop, or None when it may continue."""
        if self.redis_connector.stop.fenced:
            return "stop signal set (the connector is being deleted or paused)"

        if self.lease is not None and self.lease.is_lost():
            return "attempt lost its lease (the reaper or a cancel closed it)"

        # Check if the task has exceeded its timeout
        # NOTE: Celery's soft_time_limit does not work with thread pools,
        # so we must enforce timeouts internally.
        if self.timeout_seconds is not None:
            elapsed = time.monotonic() - self.start_monotonic
            if elapsed > self.timeout_seconds:
                logger.warning(
                    "PermissionSyncCallback - task timeout exceeded: elapsed=%ss timeout=%ss cc_pair=%s",
                    format(elapsed, ".0f"),
                    self.timeout_seconds,
                    self.redis_connector.cc_pair_id,
                )
                return (
                    f"timed out after {elapsed:.0f}s "
                    f"(PERMISSION_SYNC_TIMEOUT_SECONDS={self.timeout_seconds})"
                )

        return None

    def should_stop(self) -> bool:
        return self.stop_reason() is not None

    def progress(self, tag: str, amount: int) -> None:  # noqa: ARG002
        if self.sync_progress is not None and amount > 0:
            self.sync_progress.last_progress_at = datetime.now(timezone.utc)
