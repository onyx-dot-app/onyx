from datetime import timedelta
from typing import Any

from celery import Celery
from celery import signals
from celery.signals import beat_init

import danswer.background.celery.apps.app_base as app_base
from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import POSTGRES_CELERY_BEAT_APP_NAME
from danswer.db.engine import get_all_tenant_ids
from danswer.db.engine import SqlEngine
from danswer.utils.logger import setup_logger

logger = setup_logger()

celery_app = Celery(__name__)
celery_app.config_from_object("danswer.background.celery.configs.beat")


@beat_init.connect
def on_beat_init(sender: Any, **kwargs: Any) -> None:
    logger.info("beat_init signal received.")

    # celery beat shouldn't touch the db at all. But just setting a low minimum here.
    SqlEngine.set_app_name(POSTGRES_CELERY_BEAT_APP_NAME)
    SqlEngine.init_engine(pool_size=2, max_overflow=0)
    app_base.wait_for_redis(sender, **kwargs)


@signals.setup_logging.connect
def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    app_base.on_setup_logging(loglevel, logfile, format, colorize, **kwargs)


#####
# Celery Beat (Periodic Tasks) Settings
#####

tenant_ids = get_all_tenant_ids()

tasks_to_schedule = [
    {
        "name": "check-for-vespa-sync",
        "task": "check_for_vespa_sync_task",
        "schedule": timedelta(seconds=5),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-connector-deletion",
        "task": "check_for_connector_deletion_task",
        "schedule": timedelta(seconds=60),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-indexing",
        "task": "check_for_indexing",
        "schedule": timedelta(seconds=10),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-prune",
        "task": "check_for_pruning",
        "schedule": timedelta(seconds=10),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "kombu-message-cleanup",
        "task": "kombu_message_cleanup_task",
        "schedule": timedelta(seconds=3600),
        "options": {"priority": DanswerCeleryPriority.LOWEST},
    },
    {
        "name": "monitor-vespa-sync",
        "task": "monitor_vespa_sync",
        "schedule": timedelta(seconds=5),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
]

# Build the celery beat schedule dynamically
beat_schedule = {}

for tenant_id in tenant_ids:
    for task in tasks_to_schedule:
        task_name = f"{task['name']}-{tenant_id}"  # Unique name for each scheduled task
        beat_schedule[task_name] = {
            "task": task["task"],
            "schedule": task["schedule"],
            "options": task["options"],
            "kwargs": {"tenant_id": tenant_id},  # Must pass tenant_id as an argument
        }

# Include any existing beat schedules
existing_beat_schedule = celery_app.conf.beat_schedule or {}
beat_schedule.update(existing_beat_schedule)

# Update the Celery app configuration once
celery_app.conf.beat_schedule = beat_schedule
