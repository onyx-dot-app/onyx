import logging
import multiprocessing
import time
from typing import Any

import sentry_sdk
from celery import Task
from celery.app import trace
from celery.exceptions import WorkerShutdown
from celery.signals import task_postrun
from celery.signals import task_prerun
from celery.states import READY_STATES
from celery.utils.log import get_task_logger
from celery.worker import strategy  # type: ignore
from redis.lock import Lock as RedisLock
from sentry_sdk.integrations.celery import CeleryIntegration
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.background.celery.apps.task_formatters import CeleryTaskColoredFormatter
from onyx.background.celery.apps.task_formatters import CeleryTaskPlainFormatter
from onyx.background.celery.celery_utils import celery_is_worker_primary
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.engine import get_sqlalchemy_engine
from onyx.document_index.vespa.shared_utils.utils import get_vespa_http_client
from onyx.document_index.vespa_constants import VESPA_CONFIG_SERVER_URL
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_credential_pair import RedisConnectorCredentialPair
from onyx.redis.redis_connector_delete import RedisConnectorDelete
from onyx.redis.redis_connector_doc_perm_sync import RedisConnectorPermissionSync
from onyx.redis.redis_connector_ext_group_sync import RedisConnectorExternalGroupSync
from onyx.redis.redis_connector_prune import RedisConnectorPrune
from onyx.redis.redis_document_set import RedisDocumentSet
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_usergroup import RedisUserGroup
from onyx.utils.logger import ColoredFormatter
from onyx.utils.logger import PlainFormatter
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import SENTRY_DSN
from shared_configs.configs import TENANT_ID_PREFIX
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

task_logger = get_task_logger(__name__)

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[CeleryIntegration()],
        traces_sample_rate=0.1,
    )
    logger.info("Sentry initialized")
else:
    logger.debug("Sentry DSN not provided, skipping Sentry initialization")


def on_task_prerun(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **kwds: Any,
) -> None:
    pass


def on_task_postrun(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple | None = None,
    kwargs: dict[str, Any] | None = None,
    retval: Any | None = None,
    state: str | None = None,
    **kwds: Any,
) -> None:
    """We handle this signal in order to remove completed tasks
    from their respective tasksets. This allows us to track the progress of document set
    and user group syncs.

    This function runs after any task completes (both success and failure)
    Note that this signal does not fire on a task that failed to complete and is going
    to be retried.

    This also does not fire if a worker with acks_late=False crashes (which all of our
    long running workers are)
    """
    if not task:
        return

    task_logger.debug(f"Task {task.name} (ID: {task_id}) completed with state: {state}")

    if state not in READY_STATES:
        return

    if not task_id:
        return

    # Get tenant_id directly from kwargs- each celery task has a tenant_id kwarg
    if not kwargs:
        logger.error(f"Task {task.name} (ID: {task_id}) is missing kwargs")
        tenant_id = None
    else:
        tenant_id = kwargs.get("tenant_id")

    task_logger.debug(
        f"Task {task.name} (ID: {task_id}) completed with state: {state} "
        f"{f'for tenant_id={tenant_id}' if tenant_id else ''}"
    )

    r = get_redis_client(tenant_id=tenant_id)

    if task_id.startswith(RedisConnectorCredentialPair.PREFIX):
        r.srem(RedisConnectorCredentialPair.get_taskset_key(), task_id)
        return

    if task_id.startswith(RedisDocumentSet.PREFIX):
        document_set_id = RedisDocumentSet.get_id_from_task_id(task_id)
        if document_set_id is not None:
            rds = RedisDocumentSet(tenant_id, int(document_set_id))
            r.srem(rds.taskset_key, task_id)
        return

    if task_id.startswith(RedisUserGroup.PREFIX):
        usergroup_id = RedisUserGroup.get_id_from_task_id(task_id)
        if usergroup_id is not None:
            rug = RedisUserGroup(tenant_id, int(usergroup_id))
            r.srem(rug.taskset_key, task_id)
        return

    if task_id.startswith(RedisConnectorDelete.PREFIX):
        cc_pair_id = RedisConnector.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            RedisConnectorDelete.remove_from_taskset(int(cc_pair_id), task_id, r)
        return

    if task_id.startswith(RedisConnectorPrune.SUBTASK_PREFIX):
        cc_pair_id = RedisConnector.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            RedisConnectorPrune.remove_from_taskset(int(cc_pair_id), task_id, r)
        return

    if task_id.startswith(RedisConnectorPermissionSync.SUBTASK_PREFIX):
        cc_pair_id = RedisConnector.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            RedisConnectorPermissionSync.remove_from_taskset(
                int(cc_pair_id), task_id, r
            )
        return

    if task_id.startswith(RedisConnectorExternalGroupSync.SUBTASK_PREFIX):
        cc_pair_id = RedisConnector.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            RedisConnectorExternalGroupSync.remove_from_taskset(
                int(cc_pair_id), task_id, r
            )
        return


def on_celeryd_init(sender: Any = None, conf: Any = None, **kwargs: Any) -> None:
    """The first signal sent on celery worker startup"""
    multiprocessing.set_start_method("spawn")  # fork is unsafe, set to spawn


def wait_for_redis(sender: Any, **kwargs: Any) -> None:
    """Waits for redis to become ready subject to a hardcoded timeout.
    Will raise WorkerShutdown to kill the celery worker if the timeout is reached."""

    r = get_redis_client(tenant_id=None)

    WAIT_INTERVAL = 5
    WAIT_LIMIT = 60

    ready = False
    time_start = time.monotonic()
    logger.info("Redis: Readiness probe starting.")
    while True:
        try:
            if r.ping():
                ready = True
                break
        except Exception:
            pass

        time_elapsed = time.monotonic() - time_start
        if time_elapsed > WAIT_LIMIT:
            break

        logger.info(
            f"Redis: Readiness probe ongoing. elapsed={time_elapsed:.1f} timeout={WAIT_LIMIT:.1f}"
        )

        time.sleep(WAIT_INTERVAL)

    if not ready:
        msg = (
            f"Redis: Readiness probe did not succeed within the timeout "
            f"({WAIT_LIMIT} seconds). Exiting..."
        )
        logger.error(msg)
        raise WorkerShutdown(msg)

    logger.info("Redis: Readiness probe succeeded. Continuing...")
    return


def wait_for_db(sender: Any, **kwargs: Any) -> None:
    """Waits for the db to become ready subject to a hardcoded timeout.
    Will raise WorkerShutdown to kill the celery worker if the timeout is reached."""

    WAIT_INTERVAL = 5
    WAIT_LIMIT = 60

    ready = False
    time_start = time.monotonic()
    logger.info("Database: Readiness probe starting.")
    while True:
        try:
            with Session(get_sqlalchemy_engine()) as db_session:
                result = db_session.execute(text("SELECT NOW()")).scalar()
                if result:
                    ready = True
                    break
        except Exception:
            pass

        time_elapsed = time.monotonic() - time_start
        if time_elapsed > WAIT_LIMIT:
            break

        logger.info(
            f"Database: Readiness probe ongoing. elapsed={time_elapsed:.1f} timeout={WAIT_LIMIT:.1f}"
        )

        time.sleep(WAIT_INTERVAL)

    if not ready:
        msg = (
            f"Database: Readiness probe did not succeed within the timeout "
            f"({WAIT_LIMIT} seconds). Exiting..."
        )
        logger.error(msg)
        raise WorkerShutdown(msg)

    logger.info("Database: Readiness probe succeeded. Continuing...")
    return


def wait_for_vespa(sender: Any, **kwargs: Any) -> None:
    """Waits for Vespa to become ready subject to a hardcoded timeout.
    Will raise WorkerShutdown to kill the celery worker if the timeout is reached."""

    WAIT_INTERVAL = 5
    WAIT_LIMIT = 60

    ready = False
    time_start = time.monotonic()
    logger.info("Vespa: Readiness probe starting.")
    while True:
        try:
            client = get_vespa_http_client()
            response = client.get(f"{VESPA_CONFIG_SERVER_URL}/state/v1/health")
            response.raise_for_status()

            response_dict = response.json()
            if response_dict["status"]["code"] == "up":
                ready = True
                break
        except Exception:
            pass

        time_elapsed = time.monotonic() - time_start
        if time_elapsed > WAIT_LIMIT:
            break

        logger.info(
            f"Vespa: Readiness probe ongoing. elapsed={time_elapsed:.1f} timeout={WAIT_LIMIT:.1f}"
        )

        time.sleep(WAIT_INTERVAL)

    if not ready:
        msg = (
            f"Vespa: Readiness probe did not succeed within the timeout "
            f"({WAIT_LIMIT} seconds). Exiting..."
        )
        logger.error(msg)
        raise WorkerShutdown(msg)

    logger.info("Vespa: Readiness probe succeeded. Continuing...")
    return


def on_secondary_worker_init(sender: Any, **kwargs: Any) -> None:
    logger.info("Running as a secondary celery worker.")

    # Set up variables for waiting on primary worker
    WAIT_INTERVAL = 5
    WAIT_LIMIT = 60
    r = get_redis_client(tenant_id=None)
    time_start = time.monotonic()

    logger.info("Waiting for primary worker to be ready...")
    while True:
        if r.exists(OnyxRedisLocks.PRIMARY_WORKER):
            break

        time_elapsed = time.monotonic() - time_start
        logger.info(
            f"Primary worker is not ready yet. elapsed={time_elapsed:.1f} timeout={WAIT_LIMIT:.1f}"
        )
        if time_elapsed > WAIT_LIMIT:
            msg = (
                f"Primary worker was not ready within the timeout. "
                f"({WAIT_LIMIT} seconds). Exiting..."
            )
            logger.error(msg)
            raise WorkerShutdown(msg)

        time.sleep(WAIT_INTERVAL)

    logger.info("Wait for primary worker completed successfully. Continuing...")
    return


def on_worker_ready(sender: Any, **kwargs: Any) -> None:
    task_logger.info("worker_ready signal received.")


def on_worker_shutdown(sender: Any, **kwargs: Any) -> None:
    if not celery_is_worker_primary(sender):
        return

    if not hasattr(sender, "primary_worker_lock"):
        # primary_worker_lock will not exist when MULTI_TENANT is True
        return

    if not sender.primary_worker_lock:
        return

    logger.info("Releasing primary worker lock.")
    lock: RedisLock = sender.primary_worker_lock
    try:
        if lock.owned():
            try:
                lock.release()
                sender.primary_worker_lock = None
            except Exception:
                logger.exception("Failed to release primary worker lock")
    except Exception:
        logger.exception("Failed to check if primary worker lock is owned")


def on_setup_logging(
    loglevel: int,
    logfile: str | None,
    format: str,
    colorize: bool,
    **kwargs: Any,
) -> None:
    # TODO: could unhardcode format and colorize and accept these as options from
    # celery's config

    root_logger = logging.getLogger()
    root_logger.handlers = []

    # Define the log format
    log_format = (
        "%(levelname)-8s %(asctime)s %(filename)15s:%(lineno)-4d: %(name)s %(message)s"
    )

    # Set up the root handler
    root_handler = logging.StreamHandler()
    root_formatter = ColoredFormatter(
        log_format,
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )
    root_handler.setFormatter(root_formatter)
    root_logger.addHandler(root_handler)

    if logfile:
        root_file_handler = logging.FileHandler(logfile)
        root_file_formatter = PlainFormatter(
            log_format,
            datefmt="%m/%d/%Y %I:%M:%S %p",
        )
        root_file_handler.setFormatter(root_file_formatter)
        root_logger.addHandler(root_file_handler)

    root_logger.setLevel(loglevel)

    # Configure the task logger
    task_logger.handlers = []

    task_handler = logging.StreamHandler()
    task_handler.addFilter(TenantContextFilter())
    task_formatter = CeleryTaskColoredFormatter(
        log_format,
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )
    task_handler.setFormatter(task_formatter)
    task_logger.addHandler(task_handler)

    if logfile:
        task_file_handler = logging.FileHandler(logfile)
        task_file_handler.addFilter(TenantContextFilter())
        task_file_formatter = CeleryTaskPlainFormatter(
            log_format,
            datefmt="%m/%d/%Y %I:%M:%S %p",
        )
        task_file_handler.setFormatter(task_file_formatter)
        task_logger.addHandler(task_file_handler)

    task_logger.setLevel(loglevel)
    task_logger.propagate = False

    # hide celery task received spam
    # e.g. "Task check_for_pruning[a1e96171-0ba8-4e00-887b-9fbf7442eab3] received"
    strategy.logger.setLevel(logging.WARNING)

    # uncomment this to hide celery task succeeded/failed spam
    # e.g. "Task check_for_pruning[a1e96171-0ba8-4e00-887b-9fbf7442eab3] succeeded in 0.03137450001668185s: None"
    trace.logger.setLevel(logging.WARNING)


def set_task_finished_log_level(logLevel: int) -> None:
    """call this to override the setLevel in on_setup_logging. We are interested
    in the task timings in the cloud but it can be spammy for self hosted."""
    trace.logger.setLevel(logLevel)


class TenantContextFilter(logging.Filter):

    """Logging filter to inject tenant ID into the logger's name."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not MULTI_TENANT:
            record.name = ""
            return True

        tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
        if tenant_id:
            tenant_id = tenant_id.split(TENANT_ID_PREFIX)[-1][:5]
            record.name = f"[t:{tenant_id}]"
        else:
            record.name = ""
        return True


@task_prerun.connect
def set_tenant_id(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **other_kwargs: Any,
) -> None:
    """Signal handler to set tenant ID in context var before task starts."""
    tenant_id = (
        kwargs.get("tenant_id", POSTGRES_DEFAULT_SCHEMA)
        if kwargs
        else POSTGRES_DEFAULT_SCHEMA
    )
    CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)


@task_postrun.connect
def reset_tenant_id(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    **other_kwargs: Any,
) -> None:
    """Signal handler to reset tenant ID in context var after task ends."""
    CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
