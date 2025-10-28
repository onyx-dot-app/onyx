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
from onyx.background.celery.celery_utils import httpx_init_vespa_pool
from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_CLOUD_CERT_PATH
from onyx.configs.app_configs import VESPA_CLOUD_KEY_PATH
from onyx.configs.constants import POSTGRES_CELERY_WORKER_BACKGROUND_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT


logger = setup_logger()

celery_app = Celery(__name__)
celery_app.config_from_object("onyx.background.celery.configs.background")
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
    EXTRA_CONCURRENCY = 8  # small extra fudge factor for connection limits

    logger.info("worker_init signal received for consolidated background worker.")

    SqlEngine.set_app_name(POSTGRES_CELERY_WORKER_BACKGROUND_APP_NAME)
    pool_size = cast(int, sender.concurrency)  # type: ignore
    SqlEngine.init_engine(pool_size=pool_size, max_overflow=EXTRA_CONCURRENCY)

    # Initialize Vespa httpx pool (needed for light worker tasks)
    if MANAGED_VESPA:
        httpx_init_vespa_pool(
            sender.concurrency + EXTRA_CONCURRENCY,  # type: ignore
            ssl_cert=VESPA_CLOUD_CERT_PATH,
            ssl_key=VESPA_CLOUD_KEY_PATH,
        )
    else:
        httpx_init_vespa_pool(sender.concurrency + EXTRA_CONCURRENCY)  # type: ignore

    app_base.wait_for_redis(sender, **kwargs)
    app_base.wait_for_db(sender, **kwargs)
    app_base.wait_for_vespa_or_shutdown(sender, **kwargs)

    # Less startup checks in multi-tenant case
    if MULTI_TENANT:
        return

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


base_bootsteps = app_base.get_bootsteps()
for bootstep in base_bootsteps:
    celery_app.steps["worker"].add(bootstep)

celery_app.autodiscover_tasks(
    [
        # Original background worker tasks
        "onyx.background.celery.tasks.pruning",
        "onyx.background.celery.tasks.kg_processing",
        "onyx.background.celery.tasks.monitoring",
        "onyx.background.celery.tasks.user_file_processing",
        # Light worker tasks
        "onyx.background.celery.tasks.shared",
        "onyx.background.celery.tasks.vespa",
        "onyx.background.celery.tasks.connector_deletion",
        "onyx.background.celery.tasks.doc_permission_syncing",
        # Docprocessing worker tasks
        "onyx.background.celery.tasks.docprocessing",
        # Docfetching worker tasks
        "onyx.background.celery.tasks.docfetching",
    ]
)
