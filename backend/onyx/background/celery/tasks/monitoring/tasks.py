import time
from itertools import islice
from typing import cast

import psutil
from celery import Task, shared_task
from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from redis.lock import Lock as RedisLock
from sqlalchemy import text

from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_redis import (
    celery_get_broker_client,
    celery_get_queue_length,
    celery_get_unacked_task_ids,
)
from onyx.background.celery.memory_monitoring import emit_process_memory
from onyx.configs.constants import (
    CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    ONYX_CLOUD_TENANT_ID,
    OnyxCeleryQueues,
    OnyxCeleryTask,
    OnyxRedisLocks,
)
from onyx.db.engine.sql_engine import (
    get_session_with_shared_schema,
)
from onyx.db.engine.tenant_utils import (
    get_all_tenant_ids,
    validate_tenant_id,
)
from onyx.document_index.opensearch.resource_health import refresh_resource_health
from onyx.redis.redis_pool import (
    get_redis_client,
    redis_lock_dump,
)
from onyx.utils.fleet_telemetry import (
    CELERY_QUEUES,
    QUEUE_INTERVAL_SECONDS,
    emit_telemetry,
    get_sender,
    poll_due,
)
from onyx.utils.fleet_telemetry_collector import collect_snapshots
from onyx.utils.platform_utils import is_running_in_container, is_running_in_kubernetes
from shared_configs.configs import MULTI_TENANT

_MONITORING_SOFT_TIME_LIMIT = 60 * 5  # 5 minutes
_MONITORING_TIME_LIMIT = _MONITORING_SOFT_TIME_LIMIT + 60  # 6 minutes


@shared_task(
    name=OnyxCeleryTask.CLOUD_MONITOR_ALEMBIC,
)
def cloud_check_alembic() -> bool | None:
    """A task to verify that all tenants are on the same alembic revision.

    This check is expected to fail if a cloud alembic migration is currently running
    across all tenants.

    TODO: have the cloud migration script set an activity signal that this check
    uses to know it doesn't make sense to run a check at the present time.
    """

    # Used as a placeholder if the alembic revision cannot be retrieved
    ALEMBIC_NULL_REVISION = "000000000000"

    time_start = time.monotonic()

    redis_client = get_redis_client(tenant_id=ONYX_CLOUD_TENANT_ID)

    lock_beat: RedisLock = redis_client.lock(
        OnyxRedisLocks.CLOUD_CHECK_ALEMBIC_BEAT_LOCK,
        timeout=CELERY_GENERIC_BEAT_LOCK_TIMEOUT,
    )

    # these tasks should never overlap
    if not lock_beat.acquire(blocking=False):
        return None

    last_lock_time = time.monotonic()

    tenant_to_revision: dict[str, str] = {}
    revision_counts: dict[str, int] = {}
    out_of_date_tenants: dict[str, str] = {}
    top_revision: str = ""
    tenant_ids: list[str] | list[None] = []

    try:
        # map tenant_id to revision (or ALEMBIC_NULL_REVISION if the query fails)
        tenant_ids = get_all_tenant_ids()
        for tenant_id in tenant_ids:
            current_time = time.monotonic()
            if current_time - last_lock_time >= (CELERY_GENERIC_BEAT_LOCK_TIMEOUT / 4):
                lock_beat.reacquire()
                last_lock_time = current_time

            if tenant_id is None:
                continue

            # Defense in depth: get_all_tenant_ids() already filters with this
            # regex, but PostgreSQL cannot bind a schema identifier, so we
            # re-check at the interpolation site to keep the SQL string safe
            # even if upstream filtering ever loosens.
            if not validate_tenant_id(tenant_id):
                task_logger.warning(
                    "Skipping tenant with malformed schema name: %s", tenant_id
                )
                continue

            with get_session_with_shared_schema() as session:
                try:
                    result = session.execute(
                        text(f'SELECT * FROM "{tenant_id}".alembic_version LIMIT 1')  # noqa: S608
                    )
                    result_scalar: str | None = result.scalar_one_or_none()
                    if result_scalar is None:
                        raise ValueError("Alembic version should not be None.")

                    tenant_to_revision[tenant_id] = result_scalar
                except Exception:
                    task_logger.error(f"Tenant {tenant_id} has no revision!")
                    tenant_to_revision[tenant_id] = ALEMBIC_NULL_REVISION

        # get the total count of each revision
        for v in tenant_to_revision.values():
            revision_counts[v] = revision_counts.get(v, 0) + 1

        # error if any null revision tenants are found
        if ALEMBIC_NULL_REVISION in revision_counts:
            num_null_revisions = revision_counts[ALEMBIC_NULL_REVISION]
            raise ValueError(f"No revision was found for {num_null_revisions} tenants!")

        # get the revision with the most counts
        sorted_revision_counts = sorted(
            revision_counts.items(), key=lambda item: item[1], reverse=True
        )

        if len(sorted_revision_counts) == 0:
            raise ValueError(
                f"cloud_check_alembic - No revisions found for {len(tenant_ids)} tenant ids!"
            )

        top_revision, _ = sorted_revision_counts[0]

        # build a list of out of date tenants
        for k, v in tenant_to_revision.items():
            if v == top_revision:
                continue

            out_of_date_tenants[k] = v

    except SoftTimeLimitExceeded:
        task_logger.info(
            "Soft time limit exceeded, task is being terminated gracefully."
        )
        raise
    except Exception:
        task_logger.exception("Unexpected exception during cloud alembic check")
        raise
    finally:
        if lock_beat.owned():
            lock_beat.release()
        else:
            task_logger.error("cloud_check_alembic - Lock not owned on completion")
            redis_lock_dump(lock_beat, redis_client)

    if len(out_of_date_tenants) > 0:
        task_logger.error(
            f"Found out of date tenants: "
            f"num_out_of_date_tenants={len(out_of_date_tenants)} "
            f"num_tenants={len(tenant_ids)} "
            f"revision={top_revision}"
        )

        num_to_log = min(5, len(out_of_date_tenants))
        task_logger.info(
            f"Logging {num_to_log}/{len(out_of_date_tenants)} out of date tenants."
        )
        for k, v in islice(out_of_date_tenants.items(), 5):
            task_logger.info(f"Out of date tenant: tenant={k} revision={v}")
    else:
        task_logger.info(
            f"All tenants are up to date: num_tenants={len(tenant_ids)} revision={top_revision}"
        )

    time_elapsed = time.monotonic() - time_start
    task_logger.info(
        f"cloud_check_alembic finished: num_tenants={len(tenant_ids)} elapsed={time_elapsed:.2f}"
    )
    return True


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CLOUD_MONITOR_CELERY_QUEUES, ignore_result=True, bind=True
)
def cloud_monitor_celery_queues(
    self: Task,
) -> None:
    return monitor_celery_queues_helper(self)


@shared_task(name=OnyxCeleryTask.MONITOR_CELERY_QUEUES, ignore_result=True, bind=True)  # ty: ignore[invalid-argument-type]
def monitor_celery_queues(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    return monitor_celery_queues_helper(self)


def monitor_celery_queues_helper(
    task: Task,
) -> None:
    """A task to monitor all celery queue lengths."""

    r_celery = celery_get_broker_client(task.app)
    n_celery = celery_get_queue_length(OnyxCeleryQueues.PRIMARY, r_celery)
    n_docfetching = celery_get_queue_length(
        OnyxCeleryQueues.CONNECTOR_DOC_FETCHING, r_celery
    )
    n_docprocessing = celery_get_queue_length(OnyxCeleryQueues.DOCPROCESSING, r_celery)
    n_port = celery_get_queue_length(OnyxCeleryQueues.PORT, r_celery)

    n_user_file_processing = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILE_PROCESSING, r_celery
    )
    n_user_file_project_sync = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILE_PROJECT_SYNC, r_celery
    )
    n_user_file_delete = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILE_DELETE, r_celery
    )
    n_user_file_port = celery_get_queue_length(
        OnyxCeleryQueues.USER_FILE_PORT, r_celery
    )
    n_sync = celery_get_queue_length(OnyxCeleryQueues.VESPA_METADATA_SYNC, r_celery)
    n_deletion = celery_get_queue_length(OnyxCeleryQueues.CONNECTOR_DELETION, r_celery)
    n_pruning = celery_get_queue_length(OnyxCeleryQueues.CONNECTOR_PRUNING, r_celery)
    n_permissions_sync = celery_get_queue_length(
        OnyxCeleryQueues.CONNECTOR_DOC_PERMISSIONS_SYNC, r_celery
    )
    n_external_group_sync = celery_get_queue_length(
        OnyxCeleryQueues.CONNECTOR_EXTERNAL_GROUP_SYNC, r_celery
    )
    n_permissions_upsert = celery_get_queue_length(
        OnyxCeleryQueues.DOC_PERMISSIONS_UPSERT, r_celery
    )
    n_hierarchy_fetching = celery_get_queue_length(
        OnyxCeleryQueues.CONNECTOR_HIERARCHY_FETCHING, r_celery
    )
    n_llm_model_update = celery_get_queue_length(
        OnyxCeleryQueues.LLM_MODEL_UPDATE, r_celery
    )
    n_checkpoint_cleanup = celery_get_queue_length(
        OnyxCeleryQueues.CHECKPOINT_CLEANUP, r_celery
    )
    n_index_attempt_cleanup = celery_get_queue_length(
        OnyxCeleryQueues.INDEX_ATTEMPT_CLEANUP, r_celery
    )
    n_index_reclaim = celery_get_queue_length(OnyxCeleryQueues.INDEX_RECLAIM, r_celery)
    n_csv_generation = celery_get_queue_length(
        OnyxCeleryQueues.CSV_GENERATION, r_celery
    )
    n_capability_checks = celery_get_queue_length(
        OnyxCeleryQueues.CAPABILITY_CHECKS, r_celery
    )
    n_capability_checks_draft = celery_get_queue_length(
        OnyxCeleryQueues.CAPABILITY_CHECKS_DRAFT, r_celery
    )
    n_monitoring = celery_get_queue_length(OnyxCeleryQueues.MONITORING, r_celery)
    n_sandbox = celery_get_queue_length(OnyxCeleryQueues.SANDBOX, r_celery)

    n_docfetching_prefetched = celery_get_unacked_task_ids(
        OnyxCeleryQueues.CONNECTOR_DOC_FETCHING, r_celery
    )
    n_docprocessing_prefetched = celery_get_unacked_task_ids(
        OnyxCeleryQueues.DOCPROCESSING, r_celery
    )

    task_logger.info(
        f"Queue lengths: celery={n_celery} "
        f"docfetching={n_docfetching} "
        f"docfetching_prefetched={len(n_docfetching_prefetched)} "
        f"docprocessing={n_docprocessing} "
        f"docprocessing_prefetched={len(n_docprocessing_prefetched)} "
        f"port={n_port} "
        f"user_file_processing={n_user_file_processing} "
        f"user_file_project_sync={n_user_file_project_sync} "
        f"user_file_delete={n_user_file_delete} "
        f"user_file_port={n_user_file_port} "
        f"sync={n_sync} "
        f"deletion={n_deletion} "
        f"pruning={n_pruning} "
        f"permissions_sync={n_permissions_sync} "
        f"external_group_sync={n_external_group_sync} "
        f"permissions_upsert={n_permissions_upsert} "
        f"hierarchy_fetching={n_hierarchy_fetching} "
        f"llm_model_update={n_llm_model_update} "
        f"checkpoint_cleanup={n_checkpoint_cleanup} "
        f"index_attempt_cleanup={n_index_attempt_cleanup} "
        f"index_reclaim={n_index_reclaim} "
        f"csv_generation={n_csv_generation} "
        f"capability_checks={n_capability_checks} "
        f"capability_checks_draft={n_capability_checks_draft} "
        f"monitoring={n_monitoring} "
        f"sandbox={n_sandbox} "
    )
    _report_queue_depths(r_celery)


_last_queue_report: float | None = None


def _report_queue_depths(r_celery: Redis) -> None:
    """Fleet telemetry: the depth of every queue, at most every QUEUE_INTERVAL_SECONDS."""
    global _last_queue_report
    now: float = time.monotonic()
    if get_sender() is None or not poll_due(
        _last_queue_report, now, QUEUE_INTERVAL_SECONDS
    ):
        return
    _last_queue_report = now
    try:
        for queue in CELERY_QUEUES:
            depth: int = celery_get_queue_length(queue, r_celery)
            emit_telemetry("queue", {"queue": queue, "depth": depth, "shared": True})
    except Exception:
        # Telemetry never fails the queue monitor.
        pass


"""Memory monitoring"""


def _get_cmdline_for_process(process: psutil.Process) -> str | None:
    try:
        return " ".join(process.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _match_supervisor_processes(
    process_cmdlines: dict[int, str],
    process_type_mapping: dict[str, str],
) -> tuple[dict[int, str], list[str]]:
    """Match running processes against known supervisor-managed process
    cmdline signatures.

    Returns the pid -> process_type mapping for successfully matched
    processes, plus a list of human-readable warnings for any process
    whose type was already matched by another pid (e.g. a signature that's
    a substring of more than one running process' cmdline).
    """
    supervisor_processes: dict[int, str] = {}
    duplicate_warnings: list[str] = []

    for pid, cmdline in process_cmdlines.items():
        for process_name, process_type in process_type_mapping.items():
            if process_name in cmdline:
                if process_type in supervisor_processes.values():
                    duplicate_warnings.append(
                        f"Duplicate process type for type {process_type} with cmd {cmdline} with pid={pid}."
                    )
                    continue

                supervisor_processes[pid] = process_type
                break

    return supervisor_processes, duplicate_warnings


# Map cmd line elements to more readable process names.
# Keep in sync with the `command=`/`--hostname=` entries in
# backend/supervisord.conf. The beat signature must be specific
# enough to not also match the watchdog or log-redirect-handler
# processes, whose cmdlines reference celery_beat.log / the beat
# program name and would otherwise be misidentified as duplicates.
SUPERVISOR_PROCESS_TYPE_MAPPING = {
    "--hostname=primary": "primary",
    "--hostname=light": "light",
    "--hostname=heavy": "heavy",
    "--hostname=docprocessing": "docprocessing",
    "--hostname=user_file_processing": "user_file_processing",
    "--hostname=scheduled_tasks": "scheduled_tasks",
    "--hostname=docfetching": "docfetching",
    "--hostname=monitoring": "monitoring",
    "versioned_apps.beat beat": "beat",
    "slack/listener.py": "slack",
}


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.MONITOR_PROCESS_MEMORY,
    ignore_result=True,
    soft_time_limit=_MONITORING_SOFT_TIME_LIMIT,
    time_limit=_MONITORING_TIME_LIMIT,
    queue=OnyxCeleryQueues.MONITORING,
    bind=True,
)
def monitor_process_memory(self: Task, *, tenant_id: str) -> None:  # noqa: ARG001
    """
    Task to monitor memory usage of supervisor-managed processes.
    This periodically checks the memory usage of processes and logs information
    in a standardized format.

    The task looks for processes managed by supervisor and logs their
    memory usage statistics. This is useful for monitoring memory consumption
    over time and identifying potential memory leaks.
    """
    # don't run this task in multi-tenant mode, have other, better means of monitoring
    if MULTI_TENANT:
        return

    # Skip memory monitoring if not in container
    if not is_running_in_container():
        return

    # In k8s each worker runs in its own pod with an isolated pid namespace,
    # so psutil.process_iter() only sees the local worker.
    if is_running_in_kubernetes():
        return

    try:
        process_type_mapping = SUPERVISOR_PROCESS_TYPE_MAPPING

        # Find all python processes that are likely celery workers
        process_cmdlines: dict[int, str] = {}
        for proc in psutil.process_iter():
            cmdline = _get_cmdline_for_process(proc)
            if cmdline:
                process_cmdlines[proc.pid] = cmdline

        supervisor_processes, duplicate_warnings = _match_supervisor_processes(
            process_cmdlines, process_type_mapping
        )
        for warning in duplicate_warnings:
            task_logger.error(warning)

        missing_process_types = set(process_type_mapping.values()) - set(
            supervisor_processes.values()
        )
        if missing_process_types:
            task_logger.error(f"Missing processes: {missing_process_types}")

        # Log memory usage for each process
        for pid, process_type in supervisor_processes.items():
            try:
                emit_process_memory(pid, process_type, {})
            except psutil.NoSuchProcess:
                # Process may have terminated since we obtained the list
                continue
            except Exception as e:
                task_logger.exception(f"Error monitoring process {pid}: {str(e)}")

    except Exception:
        task_logger.exception("Error in monitor_process_memory task")


@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.CLOUD_MONITOR_CELERY_PIDBOX, ignore_result=True, bind=True
)
def cloud_monitor_celery_pidbox(
    self: Task,
) -> None:
    """
    Celery can leave behind orphaned pidboxes from old workers that are idle and never cleaned up.
    This task removes them based on idle time to avoid Redis clutter and overflowing the instance.
    This is a real issue we've observed in production.

    Note:
    - Setting CELERY_ENABLE_REMOTE_CONTROL = False would prevent pidbox keys entirely,
    but might also disable features like inspect, broadcast, and worker remote control.
    Use with caution.
    """

    num_deleted = 0

    MAX_PIDBOX_IDLE = 24 * 3600  # 1 day in seconds
    r_celery = celery_get_broker_client(self.app)
    for key in r_celery.scan_iter("*.reply.celery.pidbox"):
        key_bytes = cast(bytes, key)
        key_str = key_bytes.decode("utf-8")
        if key_str.startswith("_kombu"):
            continue

        idletime_raw = r_celery.object("idletime", key)
        if idletime_raw is None:
            continue

        idletime = cast(int, idletime_raw)
        if idletime < MAX_PIDBOX_IDLE:
            continue

        r_celery.delete(key)
        task_logger.info(
            f"Deleted idle pidbox: pidbox={key_str} idletime={idletime} max_idletime={MAX_PIDBOX_IDLE}"
        )
        num_deleted += 1

    # Enable later in case we want some aggregate metrics
    # task_logger.info(f"Deleted idle pidbox: pidbox={key_str}")


"""OpenSearch resource health"""


@shared_task(
    name=OnyxCeleryTask.MONITOR_OPENSEARCH_RESOURCES,
    ignore_result=True,
    queue=OnyxCeleryQueues.MONITORING,
)
def monitor_opensearch_resources(*, tenant_id: str | None = None) -> None:  # noqa: ARG001
    refresh_resource_health()


@shared_task(
    name=OnyxCeleryTask.COLLECT_FLEET_TELEMETRY,
    ignore_result=True,
    queue=OnyxCeleryQueues.MONITORING,
)
def collect_fleet_telemetry(*, tenant_id: str) -> None:
    collect_snapshots(tenant_id)
