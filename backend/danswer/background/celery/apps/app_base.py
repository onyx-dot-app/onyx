import logging
import multiprocessing
import time
from typing import Any

import sentry_sdk
from celery import Task
from celery.app import trace
from celery.exceptions import WorkerShutdown
from celery.states import READY_STATES
from celery.utils.log import get_task_logger
from celery.worker import strategy  # type: ignore
from sentry_sdk.integrations.celery import CeleryIntegration

from danswer.background.celery.apps.task_formatters import CeleryTaskColoredFormatter
from danswer.background.celery.apps.task_formatters import CeleryTaskPlainFormatter
from danswer.background.celery.celery_redis import RedisConnectorCredentialPair
from danswer.background.celery.celery_redis import RedisConnectorDeletion
from danswer.background.celery.celery_redis import RedisConnectorPruning
from danswer.background.celery.celery_redis import RedisDocumentSet
from danswer.background.celery.celery_redis import RedisUserGroup
from danswer.background.celery.celery_utils import celery_is_worker_primary
from danswer.configs.constants import DanswerRedisLocks
from danswer.db.engine import get_all_tenant_ids
from danswer.redis.redis_pool import get_redis_client
from danswer.utils.logger import ColoredFormatter
from danswer.utils.logger import PlainFormatter
from danswer.utils.logger import setup_logger
from shared_configs.configs import SENTRY_DSN


logger = setup_logger()

task_logger = get_task_logger(__name__)

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[CeleryIntegration()],
        traces_sample_rate=0.5,
    )
    logger.info("Sentry initialized")
else:
    logger.debug("Sentry DSN not provided, skipping Sentry initialization")


def on_task_prerun(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple | None = None,
    kwargs: dict | None = None,
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
            rds = RedisDocumentSet(int(document_set_id))
            r.srem(rds.taskset_key, task_id)
        return

    if task_id.startswith(RedisUserGroup.PREFIX):
        usergroup_id = RedisUserGroup.get_id_from_task_id(task_id)
        if usergroup_id is not None:
            rug = RedisUserGroup(int(usergroup_id))
            r.srem(rug.taskset_key, task_id)
        return

    if task_id.startswith(RedisConnectorDeletion.PREFIX):
        cc_pair_id = RedisConnectorDeletion.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            rcd = RedisConnectorDeletion(int(cc_pair_id))
            r.srem(rcd.taskset_key, task_id)
        return

    if task_id.startswith(RedisConnectorPruning.SUBTASK_PREFIX):
        cc_pair_id = RedisConnectorPruning.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            rcp = RedisConnectorPruning(int(cc_pair_id))
            r.srem(rcp.taskset_key, task_id)
        return


def on_celeryd_init(sender: Any = None, conf: Any = None, **kwargs: Any) -> None:
    """The first signal sent on celery worker startup"""
    multiprocessing.set_start_method("spawn")  # fork is unsafe, set to spawn


def wait_for_redis(sender: Any, **kwargs: Any) -> None:
    r = get_redis_client(tenant_id=None)

    WAIT_INTERVAL = 5
    WAIT_LIMIT = 60

    time_start = time.monotonic()
    logger.info("Redis: Readiness check starting.")
    while True:
        try:
            if r.ping():
                break
        except Exception:
            pass

        time_elapsed = time.monotonic() - time_start
        logger.info(
            f"Redis: Ping failed. elapsed={time_elapsed:.1f} timeout={WAIT_LIMIT:.1f}"
        )
        if time_elapsed > WAIT_LIMIT:
            msg = (
                f"Redis: Readiness check did not succeed within the timeout "
                f"({WAIT_LIMIT} seconds). Exiting..."
            )
            logger.error(msg)
            raise WorkerShutdown(msg)

        time.sleep(WAIT_INTERVAL)

    logger.info("Redis: Readiness check succeeded. Continuing...")
    return


def on_secondary_worker_init(sender: Any, **kwargs: Any) -> None:
    WAIT_INTERVAL = 5
    WAIT_LIMIT = 60

    logger.info("Running as a secondary celery worker.")
    logger.info("Waiting for all tenant primary workers to be ready...")
    time_start = time.monotonic()

    while True:
        tenant_ids = get_all_tenant_ids()
        # Check if we have a primary worker lock for each tenant
        all_tenants_ready = all(
            get_redis_client(tenant_id=tenant_id).exists(
                DanswerRedisLocks.PRIMARY_WORKER
            )
            for tenant_id in tenant_ids
        )

        if all_tenants_ready:
            break

        time_elapsed = time.monotonic() - time_start
        ready_tenants = sum(
            1
            for tenant_id in tenant_ids
            if get_redis_client(tenant_id=tenant_id).exists(
                DanswerRedisLocks.PRIMARY_WORKER
            )
        )

        logger.info(
            f"Not all tenant primary workers are ready yet. "
            f"Ready tenants: {ready_tenants}/{len(tenant_ids)} "
            f"elapsed={time_elapsed:.1f} timeout={WAIT_LIMIT:.1f}"
        )

        if time_elapsed > WAIT_LIMIT:
            msg = (
                f"Not all tenant primary workers were ready within the timeout "
                f"({WAIT_LIMIT} seconds). Exiting..."
            )
            logger.error(msg)
            raise WorkerShutdown(msg)

        time.sleep(WAIT_INTERVAL)

    logger.info("All tenant primary workers are ready. Continuing...")
    return


def on_worker_ready(sender: Any, **kwargs: Any) -> None:
    task_logger.info("worker_ready signal received.")


def on_worker_shutdown(sender: Any, **kwargs: Any) -> None:
    if not celery_is_worker_primary(sender):
        return

    if not hasattr(sender, "primary_worker_locks"):
        return

    for tenant_id, lock in sender.primary_worker_locks.items():
        try:
            if lock and lock.owned():
                logger.debug(f"Attempting to release lock for tenant {tenant_id}")
                try:
                    lock.release()
                    logger.debug(f"Successfully released lock for tenant {tenant_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to release lock for tenant {tenant_id}. Error: {str(e)}"
                    )
                finally:
                    sender.primary_worker_locks[tenant_id] = None
        except Exception as e:
            logger.error(
                f"Error checking lock status for tenant {tenant_id}. Error: {str(e)}"
            )


def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    # TODO: could unhardcode format and colorize and accept these as options from
    # celery's config

    # reformats the root logger
    root_logger = logging.getLogger()

    root_handler = logging.StreamHandler()  # Set up a handler for the root logger
    root_formatter = ColoredFormatter(
        "%(asctime)s %(filename)30s %(lineno)4s: %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )
    root_handler.setFormatter(root_formatter)
    root_logger.addHandler(root_handler)  # Apply the handler to the root logger

    if logfile:
        root_file_handler = logging.FileHandler(logfile)
        root_file_formatter = PlainFormatter(
            "%(asctime)s %(filename)30s %(lineno)4s: %(message)s",
            datefmt="%m/%d/%Y %I:%M:%S %p",
        )
        root_file_handler.setFormatter(root_file_formatter)
        root_logger.addHandler(root_file_handler)

    root_logger.setLevel(loglevel)

    # reformats celery's task logger
    task_formatter = CeleryTaskColoredFormatter(
        "%(asctime)s %(filename)30s %(lineno)4s: %(message)s",
        datefmt="%m/%d/%Y %I:%M:%S %p",
    )
    task_handler = logging.StreamHandler()  # Set up a handler for the task logger
    task_handler.setFormatter(task_formatter)
    task_logger.addHandler(task_handler)  # Apply the handler to the task logger

    if logfile:
        task_file_handler = logging.FileHandler(logfile)
        task_file_formatter = CeleryTaskPlainFormatter(
            "%(asctime)s %(filename)30s %(lineno)4s: %(message)s",
            datefmt="%m/%d/%Y %I:%M:%S %p",
        )
        task_file_handler.setFormatter(task_file_formatter)
        task_logger.addHandler(task_file_handler)

    task_logger.setLevel(loglevel)
    task_logger.propagate = False

    # hide celery task received spam
    # e.g. "Task check_for_pruning[a1e96171-0ba8-4e00-887b-9fbf7442eab3] received"
    strategy.logger.setLevel(logging.WARNING)

    # hide celery task succeeded/failed spam
    # e.g. "Task check_for_pruning[a1e96171-0ba8-4e00-887b-9fbf7442eab3] succeeded in 0.03137450001668185s: None"
    trace.logger.setLevel(logging.WARNING)
