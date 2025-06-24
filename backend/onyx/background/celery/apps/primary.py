import logging
import os
from typing import Any
from typing import cast

from celery import bootsteps  # type: ignore
from celery import Celery
from celery import signals
from celery import Task
from celery.apps.worker import Worker
from celery.exceptions import WorkerShutdown
from celery.signals import celeryd_init
from celery.signals import worker_init
from celery.signals import worker_ready
from celery.signals import worker_shutdown
from redis.lock import Lock as RedisLock

import onyx.background.celery.apps.app_base as app_base
from onyx.background.celery.apps.app_base import task_logger
from onyx.background.celery.celery_utils import celery_is_worker_primary
from onyx.background.celery.tasks.indexing.utils import (
    get_unfenced_index_attempt_ids,
)
from onyx.configs.constants import CELERY_PRIMARY_WORKER_LOCK_TIMEOUT
from onyx.configs.constants import OnyxRedisConstants
from onyx.configs.constants import OnyxRedisLocks
from onyx.configs.constants import POSTGRES_CELERY_WORKER_PRIMARY_APP_NAME
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.redis.redis_connector_credential_pair import (
    RedisGlobalConnectorCredentialPair,
)
from onyx.redis.redis_connector_delete import RedisConnectorDelete
from onyx.redis.redis_connector_doc_perm_sync import RedisConnectorPermissionSync
from onyx.redis.redis_connector_ext_group_sync import RedisConnectorExternalGroupSync
from onyx.redis.redis_connector_index import RedisConnectorIndex
from onyx.redis.redis_connector_prune import RedisConnectorPrune
from onyx.redis.redis_connector_stop import RedisConnectorStop
from onyx.redis.redis_document_set import RedisDocumentSet
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_usergroup import RedisUserGroup
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

logger = setup_logger()

celery_app = Celery(__name__)
celery_app.config_from_object("onyx.background.celery.configs.primary")
celery_app.Task = app_base.TenantAwareTask  # type: ignore [misc]


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
def on_celeryd_init(sender: str, conf: Any = None, **kwargs: Any) -> None:
    app_base.on_celeryd_init(sender, conf, **kwargs)


@worker_init.connect
def on_worker_init(sender: Worker, **kwargs: Any) -> None:
    logger.info("worker_init signal received.")

    EXTRA_CONCURRENCY = 4  # small extra fudge factor for connection limits

    SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_PRIMARY_APP_NAME)
    pool_size = cast(int, sender.concurrency)  # type: ignore
    SqlEngine.init_engine(pool_size=pool_size, max_overflow=EXTRA_CONCURRENCY)

    app_base.wait_for_redis(sender, **kwargs)
    app_base.wait_for_db(sender, **kwargs)
    app_base.wait_for_vespa_or_shutdown(sender, **kwargs)

    logger.info(f"Running as the primary celery worker: pid={os.getpid()}")

    # Less startup checks in multi-tenant case
    if MULTI_TENANT:
        return

    # This is singleton work that should be done on startup exactly once
    # by the primary worker. This is unnecessary in the multi tenant scenario
    r = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA)

    # Log the role and slave count - being connected to a slave or slave count > 0 could be problematic
    replication_info: dict[str, Any] = cast(dict, r.info("replication"))
    role: str = cast(str, replication_info.get("role", ""))
    connected_slaves: int = replication_info.get("connected_slaves", 0)

    logger.info(
        f"Redis INFO REPLICATION: role={role} connected_slaves={connected_slaves}"
    )

    memory_info: dict[str, Any] = cast(dict, r.info("memory"))
    maxmemory_policy: str = cast(str, memory_info.get("maxmemory_policy", ""))

    logger.info(f"Redis INFO MEMORY: maxmemory_policy={maxmemory_policy}")

    # For the moment, we're assuming that we are the only primary worker
    # that should be running.
    # TODO: maybe check for or clean up another zombie primary worker if we detect it
    r.delete(OnyxRedisLocks.PRIMARY_WORKER)

    # this process wide lock is taken to help other workers start up in order.
    # it is planned to use this lock to enforce singleton behavior on the primary
    # worker, since the primary worker does redis cleanup on startup, but this isn't
    # implemented yet.

    # set thread_local=False since we don't control what thread the periodic task might
    # reacquire the lock with
    lock: RedisLock = r.lock(
        OnyxRedisLocks.PRIMARY_WORKER,
        timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT,
        thread_local=False,
    )

    logger.info("Primary worker lock: Acquire starting.")
    acquired = lock.acquire(blocking_timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 2)
    if acquired:
        logger.info("Primary worker lock: Acquire succeeded.")
    else:
        logger.error("Primary worker lock: Acquire failed!")
        raise WorkerShutdown("Primary worker lock could not be acquired!")

    # tacking on our own user data to the sender
    sender.primary_worker_lock = lock  # type: ignore

    # As currently designed, when this worker starts as "primary", we reinitialize redis
    # to a clean state (for our purposes, anyway)
    r.delete(OnyxRedisLocks.CHECK_VESPA_SYNC_BEAT_LOCK)

    r.delete(OnyxRedisConstants.ACTIVE_FENCES)

    RedisGlobalConnectorCredentialPair.reset_all(r)
    RedisDocumentSet.reset_all(r)
    RedisUserGroup.reset_all(r)
    RedisConnectorDelete.reset_all(r)
    RedisConnectorPrune.reset_all(r)
    RedisConnectorIndex.reset_all(r)
    RedisConnectorStop.reset_all(r)
    RedisConnectorPermissionSync.reset_all(r)
    RedisConnectorExternalGroupSync.reset_all(r)

    # mark orphaned index attempts as failed
    with get_session_with_current_tenant() as db_session:
        unfenced_attempt_ids = get_unfenced_index_attempt_ids(db_session, r)
        for attempt_id in unfenced_attempt_ids:
            attempt = get_index_attempt(db_session, attempt_id)
            if not attempt:
                continue

            failure_reason = (
                f"Canceling leftover index attempt found on startup: "
                f"index_attempt={attempt.id} "
                f"cc_pair={attempt.connector_credential_pair_id} "
                f"search_settings={attempt.search_settings_id}"
            )
            logger.warning(failure_reason)
            logger.exception(
                f"Marking attempt {attempt.id} as canceled due to validation error 2"
            )
            mark_attempt_canceled(attempt.id, db_session, failure_reason)


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

    # this can be spammy, so just enable it in the cloud for now
    if MULTI_TENANT:
        app_base.set_task_finished_log_level(logging.INFO)


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

            if not hasattr(worker, "primary_worker_lock"):
                return

            lock: RedisLock = worker.primary_worker_lock

            r = get_redis_client(tenant_id=POSTGRES_DEFAULT_SCHEMA)

            if lock.owned():
                task_logger.debug("Reacquiring primary worker lock.")
                lock.reacquire()
            else:
                task_logger.warning(
                    "Full acquisition of primary worker lock. "
                    "Reasons could be worker restart or lock expiration."
                )
                lock = r.lock(
                    OnyxRedisLocks.PRIMARY_WORKER,
                    timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT,
                )

                task_logger.info("Primary worker lock: Acquire starting.")
                acquired = lock.acquire(
                    blocking_timeout=CELERY_PRIMARY_WORKER_LOCK_TIMEOUT / 2
                )
                if acquired:
                    task_logger.info("Primary worker lock: Acquire succeeded.")
                    worker.primary_worker_lock = lock
                else:
                    task_logger.error("Primary worker lock: Acquire failed!")
                    raise TimeoutError("Primary worker lock could not be acquired!")

        except Exception:
            task_logger.exception("Periodic task failed.")

    def stop(self, worker: Any) -> None:
        # Cancel the scheduled task when the worker stops
        if self.task_tref:
            self.task_tref.cancel()
            task_logger.info("Canceled periodic task with hub.")


celery_app.steps["worker"].add(HubPeriodicTask)

base_bootsteps = app_base.get_bootsteps()
for bootstep in base_bootsteps:
    celery_app.steps["worker"].add(bootstep)

celery_app.autodiscover_tasks(
    [
        "onyx.background.celery.tasks.connector_deletion",
        "onyx.background.celery.tasks.indexing",
        "onyx.background.celery.tasks.periodic",
        "onyx.background.celery.tasks.pruning",
        "onyx.background.celery.tasks.shared",
        "onyx.background.celery.tasks.vespa",
        "onyx.background.celery.tasks.llm_model_update",
        "onyx.background.celery.tasks.user_file_folder_sync",
        "onyx.background.celery.tasks.kg_processing",
    ]
)
