import multiprocessing
from typing import Any

from celery import Celery
from celery import signals
from celery import Task
from celery.signals import celeryd_init
from celery.signals import worker_init
from celery.signals import worker_process_init
from celery.signals import worker_ready
from celery.signals import worker_shutdown

import danswer.background.celery.apps.app_base as app_base
from danswer.configs.constants import POSTGRES_CELERY_WORKER_INDEXING_APP_NAME
from danswer.db.engine import SqlEngine
from danswer.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT


logger = setup_logger()

celery_app = Celery(__name__)
celery_app.config_from_object("danswer.background.celery.configs.indexing")


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

    SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_INDEXING_APP_NAME)
    SqlEngine.init_engine(pool_size=sender.concurrency, max_overflow=sender.concurrency)

    # Startup checks are not needed in multi-tenant case
    if MULTI_TENANT:
        return

    app_base.wait_for_redis(sender, **kwargs)
    app_base.wait_for_db(sender, **kwargs)
    app_base.wait_for_vespa(sender, **kwargs)
    app_base.on_secondary_worker_init(sender, **kwargs)


@worker_ready.connect
def on_worker_ready(sender: Any, **kwargs: Any) -> None:
    app_base.on_worker_ready(sender, **kwargs)


@worker_shutdown.connect
def on_worker_shutdown(sender: Any, **kwargs: Any) -> None:
    app_base.on_worker_shutdown(sender, **kwargs)


@worker_process_init.connect
def init_worker(**kwargs: Any) -> None:
    SqlEngine.reset_engine()


@signals.setup_logging.connect
def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    app_base.on_setup_logging(loglevel, logfile, format, colorize, **kwargs)


celery_app.autodiscover_tasks(
    [
        "danswer.background.celery.tasks.indexing",
    ]
)
