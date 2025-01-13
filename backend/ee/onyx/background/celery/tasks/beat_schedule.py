from datetime import timedelta
from typing import Any

from onyx.background.celery.tasks.beat_schedule import (
    tasks_to_schedule as base_tasks_to_schedule,
)
from onyx.configs.constants import OnyxCeleryTask

ee_tasks_to_schedule = [
    {
        "name": "autogenerate_usage_report",
        "task": OnyxCeleryTask.AUTOGENERATE_USAGE_REPORT_TASK,
        "schedule": timedelta(days=30),  # TODO: change this to config flag
    },
    {
        "name": "check-ttl-management",
        "task": OnyxCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
        "schedule": timedelta(hours=1),
    },
]


def get_tasks_to_schedule() -> list[dict[str, Any]]:
    return ee_tasks_to_schedule + base_tasks_to_schedule
