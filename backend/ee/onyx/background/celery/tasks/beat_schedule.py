from datetime import timedelta
from typing import Any

from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.background.celery.tasks.beat_schedule import (
    cloud_tasks_to_schedule as base_cloud_tasks_to_schedule,
)
from onyx.background.celery.tasks.beat_schedule import (
    tasks_to_schedule as base_tasks_to_schedule,
)
from onyx.configs.constants import ONYX_CLOUD_CELERY_TASK_PREFIX
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryTask
from shared_configs.configs import MULTI_TENANT

ee_cloud_tasks_to_schedule = [
    {
        "name": f"{ONYX_CLOUD_CELERY_TASK_PREFIX}_autogenerate-usage-report",
        "task": OnyxCeleryTask.CLOUD_BEAT_TASK_GENERATOR,
        "schedule": timedelta(days=30),
        "options": {
            "priority": OnyxCeleryPriority.HIGHEST,
            "expires": BEAT_EXPIRES_DEFAULT,
        },
        "kwargs": {
            "task_name": OnyxCeleryTask.AUTOGENERATE_USAGE_REPORT_TASK,
        },
    },
    {
        "name": f"{ONYX_CLOUD_CELERY_TASK_PREFIX}_check-ttl-management",
        "task": OnyxCeleryTask.CLOUD_BEAT_TASK_GENERATOR,
        "schedule": timedelta(hours=1),
        "options": {
            "priority": OnyxCeleryPriority.HIGHEST,
            "expires": BEAT_EXPIRES_DEFAULT,
        },
        "kwargs": {
            "task_name": OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
        },
    },
]

ee_tasks_to_schedule: list[dict] = []

if not MULTI_TENANT:
    ee_tasks_to_schedule = [
        {
            "name": "autogenerate-usage-report",
            "task": OnyxCeleryTask.AUTOGENERATE_USAGE_REPORT_TASK,
            "schedule": timedelta(days=30),  # TODO: change this to config flag
            "options": {
                "priority": OnyxCeleryPriority.MEDIUM,
                "expires": BEAT_EXPIRES_DEFAULT,
            },
        },
        {
            "name": "check-ttl-management",
            "task": OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
            "schedule": timedelta(hours=1),
            "options": {
                "priority": OnyxCeleryPriority.MEDIUM,
                "expires": BEAT_EXPIRES_DEFAULT,
            },
        },
    ]


def get_cloud_tasks_to_schedule() -> list[dict[str, Any]]:
    return ee_cloud_tasks_to_schedule + base_cloud_tasks_to_schedule


def get_tasks_to_schedule() -> list[dict[str, Any]]:
    return ee_tasks_to_schedule + base_tasks_to_schedule
