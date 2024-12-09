import logging
import multiprocessing
import time
from typing import Any

import requests
import sentry_sdk
from celery import Task
from celery.app import trace
from celery.exceptions import WorkerShutdown
from celery.states import READY_STATES
from celery.utils.log import get_task_logger
from celery.worker import strategy  # type: ignore
from sentry_sdk.integrations.celery import CeleryIntegration
from sqlalchemy import text
from sqlalchemy.orm import Session

from danswer.background.celery.apps.task_formatters import CeleryTaskColoredFormatter
from danswer.background.celery.apps.task_formatters import CeleryTaskPlainFormatter
from danswer.background.celery.celery_utils import celery_is_worker_primary
from danswer.configs.constants import DanswerRedisLocks
from danswer.db.engine import get_sqlalchemy_engine
from danswer.document_index.vespa_constants import VESPA_CONFIG_SERVER_URL
from danswer.redis.redis_connector import RedisConnector
from danswer.redis.redis_connector_credential_pair import RedisConnectorCredentialPair
from danswer.redis.redis_connector_delete import RedisConnectorDelete
from danswer.redis.redis_connector_doc_perm_sync import RedisConnectorPermissionSync
from danswer.redis.redis_connector_ext_group_sync import RedisConnectorExternalGroupSync
from danswer.redis.redis_connector_prune import RedisConnectorPrune
from danswer.redis.redis_document_set import RedisDocumentSet
from danswer.redis.redis_pool import get_redis_client
from danswer.redis.redis_usergroup import RedisUserGroup
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
        traces_sample_rate=0.1,
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
            response = requests.get(f"{VESPA_CONFIG_SERVER_URL}/state/v1/health")
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
        if r.exists(DanswerRedisLocks.PRIMARY_WORKER):
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

    if not sender.primary_worker_lock:
        return

    logger.info("Releasing primary worker lock.")
    lock = sender.primary_worker_lock
    try:
        if lock.owned():
            try:
                lock.release()
                sender.primary_worker_lock = None
            except Exception as e:
                logger.error(f"Failed to release primary worker lock: {e}")
    except Exception as e:
        logger.error(f"Failed to check if primary worker lock is owned: {e}")


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
