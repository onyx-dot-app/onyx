import multiprocessing
from typing import Any

from celery import bootsteps  # type: ignore
from celery import Celery
from celery import signals
from celery import Task
from celery.exceptions import WorkerShutdown
from celery.signals import celeryd_init
from celery.signals import worker_init
from celery.signals import worker_ready
from celery.signals import worker_shutdown

import danswer.background.celery.apps.app_base as app_base
from danswer.background.celery.apps.app_base import task_logger
from danswer.background.celery.celery_redis import RedisConnectorCredentialPair
from danswer.background.celery.celery_redis import RedisConnectorDeletion
from danswer.background.celery.celery_redis import RedisConnectorIndexing
from danswer.background.celery.celery_redis import RedisConnectorPruning
from danswer.background.celery.celery_redis import RedisConnectorStop
from danswer.background.celery.celery_redis import RedisDocumentSet
from danswer.background.celery.celery_redis import RedisUserGroup
from danswer.background.celery.celery_utils import celery_is_worker_primary
from danswer.configs.constants import CELERY_PRIMARY_WORKER_LOCK_TIMEOUT
from danswer.configs.constants import DanswerRedisLocks
from danswer.configs.constants import POSTGRES_CELERY_WORKER_PRIMARY_APP_NAME
from danswer.db.engine import get_all_tenant_ids
from danswer.db.engine import SqlEngine
from danswer.redis.redis_pool import get_redis_client
from danswer.utils.logger import setup_logger


logger = setup_logger()

celery_app = Celery(__name__)
celery_app.config_from_object("danswer.background.celery.configs.primary")


@signals.task_prerun.connect
def on_task_prerun(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple | None = None,
    kwargs: dict | None = None,
    **kwds: Any,
) -> None:
    app_base.on_task_prerun(sender, task_id, task, args, kwargs, **kwds)


@signals.task_postrun.connect
def on_task_postrun(
    sender: Any | None = None,
    task_id: str | None = None,
    task: Task | None = None,
    args: tuple | None = None,
    kwargs: dict | None = None,
    retval: Any | None = None,
    state: str | None = None,
    **kwds: Any,
) -> None:
    app_base.on_task_postrun(sender, task_id, task, args, kwargs, retval, state, **kwds)


@celeryd_init.connect
def on_celeryd_init(sender: Any = None, conf: Any = None, **kwargs: Any) -> None:
    app_base.on_celeryd_init(sender, conf, **kwargs)


@worker_init.connect
def on_worker_init(sender: Any, **kwargs: Any) -> None:
    logger.info("worker_init signal received.")
    logger.info(f"Multiprocessing start method: {multiprocessing.get_start_method()}")

    SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_PRIMARY_APP_NAME)
    SqlEngine.init_engine(pool_size=8, max_overflow=0)

    app_base.wait_for_redis(sender, **kwargs)

    logger.info("Running as the primary celery worker.")

    sender.primary_worker_locks = {}

    # This is singleton work that should be done on startup exactly once
    # by the primary worker
    tenant_ids = get_all_tenant_ids()
    for tenant_id in tenant_ids:
        r = get_redis_client(tenant_id=tenant_id)

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

        # tacking on our own user data to the sender
        sender.primary_worker_locks[tenant_id] = lock

        # As currently designed, when this worker starts as "primary", we reinitialize redis
        # to a clean state (for our purposes, anyway)
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

        for key in r.scan_iter(RedisConnectorIndexing.TASKSET_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndexing.GENERATOR_COMPLETE_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndexing.GENERATOR_PROGRESS_PREFIX + "*"):
            r.delete(key)

        for key in r.scan_iter(RedisConnectorIndexing.FENCE_PREFIX + "*"):
            r.delete(key)

    for key in r.scan_iter(RedisConnectorStop.FENCE_PREFIX + "*"):
        r.delete(key)


@worker_ready.connect
def on_worker_ready(sender: Any, **kwargs: Any) -> None:
    app_base.on_worker_ready(sender, **kwargs)


@worker_shutdown.connect
def on_worker_shutdown(sender: Any, **kwargs: Any) -> None:
    app_base.on_worker_shutdown(sender, **kwargs)


@signals.setup_logging.connect
def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    app_base.on_setup_logging(loglevel, logfile, format, colorize, **kwargs)


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
            if not celery_is_worker_primary(worker):
                return

            if not hasattr(worker, "primary_worker_locks"):
                return

            # Retrieve all tenant IDs
            tenant_ids = get_all_tenant_ids()

            for tenant_id in tenant_ids:
                lock = worker.primary_worker_locks.get(tenant_id)
                if not lock:
                    continue  # Skip if no lock for this tenant

                r = get_redis_client(tenant_id=tenant_id)

                if lock.owned():
                    task_logger.debug(
                        f"Reacquiring primary worker lock for tenant {tenant_id}."
                    )
                    lock.reacquire()
                else:
                    task_logger.warning(
                        f"Full acquisition of primary worker lock for tenant {tenant_id}. "
                        "Reasons could be worker restart or lock expiration."
                    )
                    lock = r.lock(
                        DanswerRedisLocks.PRIMARY_WORKER,
                        timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT,
                    )

                    task_logger.info(
                        f"Primary worker lock for tenant {tenant_id}: Acquire starting."
                    )
                    acquired = lock.acquire(
                        blocking_timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 2
                    )
                    if acquired:
                        task_logger.info(
                            f"Primary worker lock for tenant {tenant_id}: Acquire succeeded."
                        )
                        worker.primary_worker_locks[tenant_id] = lock
                    else:
                        task_logger.error(
                            f"Primary worker lock for tenant {tenant_id}: Acquire failed!"
                        )
                        raise TimeoutError(
                            f"Primary worker lock for tenant {tenant_id} could not be acquired!"
                        )

        except Exception:
            task_logger.exception("Periodic task failed.")

    def stop(self, worker: Any) -> None:
        # Cancel the scheduled task when the worker stops
        if self.task_tref:
            self.task_tref.cancel()
            task_logger.info("Canceled periodic task with hub.")


celery_app.steps["worker"].add(HubPeriodicTask)

celery_app.autodiscover_tasks(
    [
        "danswer.background.celery.tasks.connector_deletion",
        "danswer.background.celery.tasks.indexing",
        "danswer.background.celery.tasks.periodic",
        "danswer.background.celery.tasks.pruning",
        "danswer.background.celery.tasks.shared",
        "danswer.background.celery.tasks.vespa",
    ]
)
