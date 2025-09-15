from datetime import timedelta
from typing import Any

from ee.onyx.configs.app_configs import CHECK_TTL_MANAGEMENT_TASK_FREQUENCY_IN_HOURS
from onyx.background.celery.tasks.beat_schedule import (
    beat_cloud_tasks as base_beat_system_tasks,
)
from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.background.celery.tasks.beat_schedule import (
    beat_task_templates as base_beat_task_templates,
)
from onyx.background.celery.tasks.beat_schedule import generate_cloud_tasks
from onyx.background.celery.tasks.beat_schedule import (
    get_tasks_to_schedule as base_get_tasks_to_schedule,
)
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from shared_configs.configs import MULTI_TENANT

ee_beat_system_tasks: list[dict] = []

ee_beat_task_templates: list[dict] = [
    {
        "name": "autogenerate-usage-report",
        "task": OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK,
        "schedule": timedelta(days=30),
        "options": {
            "priority": OnyxCeleryPriority.MEDIUM,
            "expires": BEAT_EXPIRES_DEFAULT,
        },
    },
    {
        "name": "check-ttl-management",
        "task": OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
        "schedule": timedelta(hours=CHECK_TTL_MANAGEMENT_TASK_FREQUENCY_IN_HOURS),
        "options": {
            "priority": OnyxCeleryPriority.MEDIUM,
            "expires": BEAT_EXPIRES_DEFAULT,
        },
    },
    {
        "name": "export-query-history-cleanup-task",
        "task": OnyxCeleryTask.EXPORT_QUERY_HISTORY_CLEANUP_TASK,
        "schedule": timedelta(hours=1),
        "options": {
            "priority": OnyxCeleryPriority.MEDIUM,
            "expires": BEAT_EXPIRES_DEFAULT,
            "queue": OnyxCeleryQueues.CSV_GENERATION,
        },
    },
]

ee_tasks_to_schedule: list[dict] = []

if not MULTI_TENANT:
    ee_tasks_to_schedule = [
        {
            "name": "autogenerate-usage-report",
            "task": OnyxCeleryTask.GENERATE_USAGE_REPORT_TASK,
            "schedule": timedelta(days=30),  # TODO: change this to config flag
            "options": {
                "priority": OnyxCeleryPriority.MEDIUM,
                "expires": BEAT_EXPIRES_DEFAULT,
            },
        },
        {
            "name": "check-ttl-management",
            "task": OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
            "schedule": timedelta(hours=CHECK_TTL_MANAGEMENT_TASK_FREQUENCY_IN_HOURS),
            "options": {
                "priority": OnyxCeleryPriority.MEDIUM,
                "expires": BEAT_EXPIRES_DEFAULT,
            },
        },
        {
            "name": "export-query-history-cleanup-task",
            "task": OnyxCeleryTask.EXPORT_QUERY_HISTORY_CLEANUP_TASK,
            "schedule": timedelta(hours=1),
            "options": {
                "priority": OnyxCeleryPriority.MEDIUM,
                "expires": BEAT_EXPIRES_DEFAULT,
                "queue": OnyxCeleryQueues.CSV_GENERATION,
            },
        },
    ]


def get_cloud_tasks_to_schedule(beat_multiplier: float) -> list[dict[str, Any]]:
    beat_system_tasks = ee_beat_system_tasks + base_beat_system_tasks
    beat_task_templates = ee_beat_task_templates + base_beat_task_templates
    cloud_tasks = generate_cloud_tasks(
        beat_system_tasks, beat_task_templates, beat_multiplier
    )
    return cloud_tasks


def get_tasks_to_schedule() -> list[dict[str, Any]]:
    return ee_tasks_to_schedule + base_get_tasks_to_schedule()
