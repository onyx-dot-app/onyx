from typing import Any
from typing import cast

from celery import Celery
from celery import signals
from celery import Task
from celery.apps.worker import Worker
from celery.signals import celeryd_init
from celery.signals import worker_init
from celery.signals import worker_process_init
from celery.signals import worker_ready
from celery.signals import worker_shutdown

import onyx.background.celery.apps.app_base as app_base
from onyx.configs.constants import POSTGRES_CELERY_WORKER_DOCPROCESSING_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.server.metrics.celery_task_metrics import on_celery_task_postrun
from onyx.server.metrics.celery_task_metrics import on_celery_task_prerun
from onyx.server.metrics.celery_task_metrics import on_celery_task_rejected
from onyx.server.metrics.celery_task_metrics import on_celery_task_retry
from onyx.server.metrics.celery_task_metrics import on_celery_task_revoked
from onyx.server.metrics.indexing_task_metrics import on_indexing_task_postrun
from onyx.server.metrics.indexing_task_metrics import on_indexing_task_prerun
from onyx.server.metrics.metrics_server import start_metrics_server
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

celery_app = Celery(__name__)
celery_app.config_from_object("onyx.background.celery.configs.docprocessing")
celery_app.Task = app_base.TenantAwareTask  # ty: ignore[invalid-assignment]


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
    on_celery_task_prerun(task_id, task)
    on_indexing_task_prerun(task_id, task, kwargs)


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
    on_celery_task_postrun(task_id, task, state)
    on_indexing_task_postrun(task_id, task, kwargs, state)


@signals.task_retry.connect
def on_task_retry(sender: Any | None = None, **kwargs: Any) -> None:  # noqa: ARG001
    # task_retry signal doesn't pass task_id in kwargs; get it from
    # the sender (the task instance) via sender.request.id.
    task_id = getattr(getattr(sender, "request", None), "id", None)
    on_celery_task_retry(task_id, sender)


@signals.task_revoked.connect
def on_task_revoked(sender: Any | None = None, **kwargs: Any) -> None:
    task_name = getattr(sender, "name", None) or str(sender)
    on_celery_task_revoked(kwargs.get("task_id"), task_name)


@signals.task_rejected.connect
def on_task_rejected(sender: Any | None = None, **kwargs: Any) -> None:  # noqa: ARG001
    # task_rejected sends the Consumer as sender, not the task instance.
    # The task name must be extracted from the Celery message headers.
    message = kwargs.get("message")
    task_name: str | None = None
    if message is not None:
        headers = getattr(message, "headers", None) or {}
        task_name = headers.get("task")
    if task_name is None:
        task_name = "unknown"
    on_celery_task_rejected(None, task_name)


@celeryd_init.connect
def on_celeryd_init(sender: str, conf: Any = None, **kwargs: Any) -> None:
    app_base.on_celeryd_init(sender, conf, **kwargs)


@worker_init.connect
def on_worker_init(sender: Worker, **kwargs: Any) -> None:
    logger.info("worker_init signal received.")

    SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_DOCPROCESSING_APP_NAME)

    # rkuo: Transient errors keep happening in the indexing watchdog threads.
    # "SSL connection has been closed unexpectedly"
    # actually setting the spawn method in the cloud fixes 95% of these.
    # setting pre ping might help even more, but not worrying about that yet
    pool_size = cast(int, sender.concurrency)  # ty: ignore[unresolved-attribute]
    SqlEngine.init_engine(pool_size=pool_size, max_overflow=8)

    app_base.wait_for_redis(sender, **kwargs)
    app_base.wait_for_db(sender, **kwargs)
    app_base.wait_for_document_index_or_shutdown()

    # Less startup checks in multi-tenant case
    if MULTI_TENANT:
        return

    app_base.on_secondary_worker_init(sender, **kwargs)


@worker_ready.connect
def on_worker_ready(sender: Any, **kwargs: Any) -> None:
    start_metrics_server("docprocessing")
    app_base.on_worker_ready(sender, **kwargs)


@worker_shutdown.connect
def on_worker_shutdown(sender: Any, **kwargs: Any) -> None:
    app_base.on_worker_shutdown(sender, **kwargs)


# Note: worker_process_init only fires in prefork pool mode. Docprocessing uses
# worker_pool="threads" (see configs/docprocessing.py), so this handler is
# effectively a no-op in normal operation. It remains as a safety net in case
# the pool type is ever changed to prefork. Prometheus metrics are safe in
# thread-pool mode since all threads share the same process memory and can
# update the same Counter/Gauge/Histogram objects directly.
@worker_process_init.connect
def init_worker(**kwargs: Any) -> None:  # noqa: ARG001
    SqlEngine.reset_engine()


@signals.setup_logging.connect
def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    app_base.on_setup_logging(loglevel, logfile, format, colorize, **kwargs)


base_bootsteps = app_base.get_bootsteps()
for bootstep in base_bootsteps:
    celery_app.steps["worker"].add(bootstep)

celery_app.autodiscover_tasks(
    app_base.filter_task_modules(
        [
            "onyx.background.celery.tasks.docprocessing",
        ]
    )
)
