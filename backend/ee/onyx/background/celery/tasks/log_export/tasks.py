from pathlib import Path

from celery import shared_task

from ee.onyx.server.log_export.collection import get_default_log_directories
from ee.onyx.server.log_export.storage import (
    collect_logs_into_file_store,
    delete_expired_log_exports,
)
from onyx.configs.app_configs import JOB_TIMEOUT
from onyx.configs.constants import OnyxCeleryTask
from onyx.utils.logger import setup_logger
from onyx.utils.platform_utils import is_running_in_container

logger = setup_logger()

# Supervisord captures each worker program's stdout to
# ``/var/log/<program>.log`` in the Compose ``background`` container. Only the
# top level is searched: its subdirectories hold system logs (e.g. ``apt/``),
# not Onyx logs.
SUPERVISORD_LOG_DIRECTORY = Path("/var/log")


# TODO(andrei): Kubernetes coverage is partial by design as of now. A celery
# queue delivers each collect task to exactly ONE consumer, so with HPA-scaled
# workers (replicas > 1) only one pod per worker type is sampled, and nothing
# marks the unsampled replicas; stdout-only / read-only-root pods report
# ``no_logs_found``. The plan in the future is a ``pods/log`` API collector
# (optional namespace-scoped RBAC: ``pods`` get/list + ``pods/log`` get) that
# covers every replica, stdout-only pods, and crashed containers via
# ``previous=True``.
@shared_task(
    name=OnyxCeleryTask.EXPORT_LOGS_COLLECT_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def export_logs_collect_task(
    *,
    export_id: str,
    worker_name: str,
) -> None:
    """Collects this container's log files into the file store."""
    shallow_log_directories = (
        [SUPERVISORD_LOG_DIRECTORY] if is_running_in_container() else []
    )
    receipt = collect_logs_into_file_store(
        export_id=export_id,
        worker_name=worker_name,
        log_directories=get_default_log_directories(),
        shallow_log_directories=shallow_log_directories,
    )
    logger.info(
        "Log export collection finished: export_id=%s worker_name=%s "
        "status=%s file_count=%d",
        export_id,
        worker_name,
        receipt.status.value,
        receipt.file_count,
    )


@shared_task(
    name=OnyxCeleryTask.EXPORT_LOGS_CLEANUP_TASK,
    ignore_result=True,
    soft_time_limit=JOB_TIMEOUT,
)
def export_logs_cleanup_task(
    *,
    tenant_id: str,  # noqa: ARG001  # Injected into every beat task by ``DynamicTenantScheduler``.
) -> None:
    """Deletes log-export artifacts past their retention window."""
    delete_expired_log_exports()
