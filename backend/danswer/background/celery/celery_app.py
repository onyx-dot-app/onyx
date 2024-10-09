import logging
import time
from datetime import timedelta
from typing import Any

import redis
from celery import bootsteps  # type: ignore
from celery import Celery
from celery import current_task
from celery import signals
from celery import Task
from celery.exceptions import WorkerShutdown
from celery.signals import beat_init
from celery.signals import worker_init
from celery.signals import worker_ready
from celery.signals import worker_shutdown
from celery.states import READY_STATES
from celery.utils.log import get_task_logger

from danswer.background.celery.celery_redis import RedisConnectorCredentialPair
from danswer.background.celery.celery_redis import RedisConnectorDeletion
from danswer.background.celery.celery_redis import RedisConnectorPruning
from danswer.background.celery.celery_redis import RedisDocumentSet
from danswer.background.celery.celery_redis import RedisUserGroup
from danswer.background.celery.celery_utils import celery_is_worker_primary
from danswer.configs.constants import CELERY_PRIMARY_WORKER_LOCK_TIMEOUT
from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import DanswerRedisLocks
from danswer.configs.constants import POSTGRES_CELERY_BEAT_APP_NAME
from danswer.configs.constants import POSTGRES_CELERY_WORKER_HEAVY_APP_NAME
from danswer.configs.constants import POSTGRES_CELERY_WORKER_LIGHT_APP_NAME
from danswer.configs.constants import POSTGRES_CELERY_WORKER_PRIMARY_APP_NAME
from danswer.db.engine import SqlEngine
from danswer.redis.redis_pool import get_redis_client
from danswer.utils.logger import ColoredFormatter
from danswer.utils.logger import PlainFormatter
from danswer.utils.logger import setup_logger

logger = setup_logger()

# use this within celery tasks to get celery task specific logging
task_logger = get_task_logger(__name__)

celery_app = Celery(__name__)
celery_app.config_from_object(
    "danswer.background.celery.celeryconfig"
)  # Load configuration from 'celeryconfig.py'


@signals.task_postrun.connect
def celery_task_postrun(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple | None = None,
    kwargs: dict | None = None,
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
    """
    if not task:
        return

    task_logger.debug(f"Task {task.name} (ID: {task_id}) completed with state: {state}")
    # logger.debug(f"Result: {retval}")

    if state not in READY_STATES:
        return

    if not task_id:
        return

    r = get_redis_client()

    if task_id.startswith(RedisConnectorCredentialPair.PREFIX):
        r.srem(RedisConnectorCredentialPair.get_taskset_key(), task_id)
        return

    if task_id.startswith(RedisDocumentSet.PREFIX):
        document_set_id = RedisDocumentSet.get_id_from_task_id(task_id)
        if document_set_id is not None:
            rds = RedisDocumentSet(document_set_id)
            r.srem(rds.taskset_key, task_id)
        return

    if task_id.startswith(RedisUserGroup.PREFIX):
        usergroup_id = RedisUserGroup.get_id_from_task_id(task_id)
        if usergroup_id is not None:
            rug = RedisUserGroup(usergroup_id)
            r.srem(rug.taskset_key, task_id)
        return

    if task_id.startswith(RedisConnectorDeletion.PREFIX):
        cc_pair_id = RedisConnectorDeletion.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            rcd = RedisConnectorDeletion(cc_pair_id)
            r.srem(rcd.taskset_key, task_id)
        return

    if task_id.startswith(RedisConnectorPruning.SUBTASK_PREFIX):
        cc_pair_id = RedisConnectorPruning.get_id_from_task_id(task_id)
        if cc_pair_id is not None:
            rcp = RedisConnectorPruning(cc_pair_id)
            r.srem(rcp.taskset_key, task_id)
        return


@beat_init.connect
def on_beat_init(sender: Any, **kwargs: Any) -> None:
    SqlEngine.set_app_name(POSTGRES_CELERY_BEAT_APP_NAME)
    SqlEngine.init_engine(pool_size=2, max_overflow=0)


@worker_init.connect
def on_worker_init(sender: Any, **kwargs: Any) -> None:
    # decide some initial startup settings based on the celery worker's hostname
    # (set at the command line)
    hostname = sender.hostname
    if hostname.startswith("light"):
        SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_LIGHT_APP_NAME)
        SqlEngine.init_engine(pool_size=sender.concurrency, max_overflow=8)
    elif hostname.startswith("heavy"):
        SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_HEAVY_APP_NAME)
        SqlEngine.init_engine(pool_size=8, max_overflow=0)
    else:
        SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_PRIMARY_APP_NAME)
        SqlEngine.init_engine(pool_size=8, max_overflow=0)

    r = get_redis_client()

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

    if not celery_is_worker_primary(sender):
        logger.info("Running as a secondary celery worker.")
        logger.info("Waiting for primary worker to be ready...")
        time_start = time.monotonic()
        while True:
            if r.exists(DanswerRedisLocks.PRIMARY_WORKER):
                break

            time.monotonic()
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

    logger.info("Running as the primary celery worker.")

    # This is singleton work that should be done on startup exactly once
    # by the primary worker
    r = get_redis_client()

    # For the moment, we're assuming that we are the only primary worker
    # that should be running.
    # TODO: maybe check for or clean up another zombie primary worker if we detect it
    r.delete(DanswerRedisLocks.PRIMARY_WORKER)

    # this process wide lock is taken to help other workers start up in order.
    # it is planned to use this lock to enforce singleton behavior on the primary
    # worker, since the primary worker does redis cleanup on startup, but this isn't
    # implemented yet.
    lock = r.lock(
        DanswerRedisLocks.PRIMARY_WORKER,
        timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT,
    )

    logger.info("Primary worker lock: Acquire starting.")
    acquired = lock.acquire(blocking_timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 2)
    if acquired:
        logger.info("Primary worker lock: Acquire succeeded.")
    else:
        logger.error("Primary worker lock: Acquire failed!")
        raise WorkerShutdown("Primary worker lock could not be acquired!")

    sender.primary_worker_lock = lock

    r.delete(DanswerRedisLocks.CHECK_VESPA_SYNC_BEAT_LOCK)
    r.delete(DanswerRedisLocks.MONITOR_VESPA_SYNC_BEAT_LOCK)

    r.delete(RedisConnectorCredentialPair.get_taskset_key())
    r.delete(RedisConnectorCredentialPair.get_fence_key())

    for key in r.scan_iter(RedisDocumentSet.TASKSET_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisDocumentSet.FENCE_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisUserGroup.TASKSET_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisUserGroup.FENCE_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisConnectorDeletion.TASKSET_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisConnectorDeletion.FENCE_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisConnectorPruning.TASKSET_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisConnectorPruning.GENERATOR_COMPLETE_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisConnectorPruning.GENERATOR_PROGRESS_PREFIX + "*"):
        r.delete(key)

    for key in r.scan_iter(RedisConnectorPruning.FENCE_PREFIX + "*"):
        r.delete(key)


@worker_ready.connect
def on_worker_ready(sender: Any, **kwargs: Any) -> None:
    task_logger.info("worker_ready signal received.")


@worker_shutdown.connect
def on_worker_shutdown(sender: Any, **kwargs: Any) -> None:
    if not celery_is_worker_primary(sender):
        return

    if not sender.primary_worker_lock:
        return

    logger.info("Releasing primary worker lock.")
    lock = sender.primary_worker_lock
    if lock.owned():
        lock.release()
        sender.primary_worker_lock = None


class CeleryTaskPlainFormatter(PlainFormatter):
    def format(self, record: logging.LogRecord) -> str:
        task = current_task
        if task and task.request:
            record.__dict__.update(task_id=task.request.id, task_name=task.name)
            record.msg = f"[{task.name}({task.request.id})] {record.msg}"

        return super().format(record)


class CeleryTaskColoredFormatter(ColoredFormatter):
    def format(self, record: logging.LogRecord) -> str:
        task = current_task
        if task and task.request:
            record.__dict__.update(task_id=task.request.id, task_name=task.name)
            record.msg = f"[{task.name}({task.request.id})] {record.msg}"

        return super().format(record)


@signals.setup_logging.connect
def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    # TODO: could unhardcode format and colorize and accept these as options from
    # celery's config

    # reformats celery's worker logger
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


class HubPeriodicTask(bootsteps.StartStopStep):
    """Regularly reacquires the primary worker lock outside of the task queue.
    Use the task_logger in this class to avoid double logging.

    This cannot be done inside a regular beat task because it must run on schedule and
    a queue of existing work would starve the task from running.
    """

    # it's unclear to me whether using the hub's timer or the bootstep timer is better
    requires = {"celery.worker.components:Hub"}

    def __init__(self, worker: Any, **kwargs: Any) -> None:
        self.interval = CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 8  # Interval in seconds
        self.task_tref = None

    def start(self, worker: Any) -> None:
        if not celery_is_worker_primary(worker):
            return

        # Access the worker's event loop (hub)
        hub = worker.consumer.controller.hub

        # Schedule the periodic task
        self.task_tref = hub.call_repeatedly(
            self.interval, self.run_periodic_task, worker
        )
        task_logger.info("Scheduled periodic task with hub.")

    def run_periodic_task(self, worker: Any) -> None:
        try:
            if not worker.primary_worker_lock:
                return

            if not hasattr(worker, "primary_worker_lock"):
                return

            r = get_redis_client()

            lock: redis.lock.Lock = worker.primary_worker_lock

            if lock.owned():
                task_logger.debug("Reacquiring primary worker lock.")
                lock.reacquire()
            else:
                task_logger.warning(
                    "Full acquisition of primary worker lock. "
                    "Reasons could be computer sleep or a clock change."
                )
                lock = r.lock(
                    DanswerRedisLocks.PRIMARY_WORKER,
                    timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT,
                )

                task_logger.info("Primary worker lock: Acquire starting.")
                acquired = lock.acquire(
                    blocking_timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 2
                )
                if acquired:
                    task_logger.info("Primary worker lock: Acquire succeeded.")
                else:
                    task_logger.error("Primary worker lock: Acquire failed!")
                    raise TimeoutError("Primary worker lock could not be acquired!")

                worker.primary_worker_lock = lock
        except Exception:
            task_logger.exception("HubPeriodicTask.run_periodic_task exceptioned.")

    def stop(self, worker: Any) -> None:
        # Cancel the scheduled task when the worker stops
        if self.task_tref:
            self.task_tref.cancel()
            task_logger.info("Canceled periodic task with hub.")


celery_app.steps["worker"].add(HubPeriodicTask)

celery_app.autodiscover_tasks(
    [
        "danswer.background.celery.tasks.connector_deletion",
        "danswer.background.celery.tasks.periodic",
        "danswer.background.celery.tasks.pruning",
        "danswer.background.celery.tasks.shared",
        "danswer.background.celery.tasks.vespa",
    ]
)

#####
# Celery Beat (Periodic Tasks) Settings
#####
celery_app.conf.beat_schedule = {
    "check-for-vespa-sync": {
        "task": "check_for_vespa_sync_task",
        "schedule": timedelta(seconds=5),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
}
celery_app.conf.beat_schedule.update(
    {
        "check-for-connector-deletion-task": {
            "task": "check_for_connector_deletion_task",
            # don't need to check too often, since we kick off a deletion initially
            # during the API call that actually marks the CC pair for deletion
            "schedule": timedelta(seconds=60),
            "options": {"priority": DanswerCeleryPriority.HIGH},
        },
    }
)
celery_app.conf.beat_schedule.update(
    {
        "check-for-prune": {
            "task": "check_for_prune_task_2",
            "schedule": timedelta(seconds=60),
            "options": {"priority": DanswerCeleryPriority.HIGH},
        },
    }
)
celery_app.conf.beat_schedule.update(
    {
        "kombu-message-cleanup": {
            "task": "kombu_message_cleanup_task",
            "schedule": timedelta(seconds=3600),
            "options": {"priority": DanswerCeleryPriority.LOWEST},
        },
    }
)
celery_app.conf.beat_schedule.update(
    {
        "monitor-vespa-sync": {
            "task": "monitor_vespa_sync",
            "schedule": timedelta(seconds=5),
            "options": {"priority": DanswerCeleryPriority.HIGH},
        },
    }
)
