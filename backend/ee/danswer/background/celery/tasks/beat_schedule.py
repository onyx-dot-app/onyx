from datetime import timedelta
from typing import Any

from danswer.background.celery.tasks.beat_schedule import (
    tasks_to_schedule as base_tasks_to_schedule,
)
from danswer.configs.constants import DanswerCeleryTask

ee_tasks_to_schedule = [
    {
        "name": "autogenerate_usage_report",
        "task": DanswerCeleryTask.AUTOGENERATE_USAGE_REPORT_TASK,
        "schedule": timedelta(days=30),  # TODO: change this to config flag
    },
    {
        "name": "check-ttl-management",
        "task": DanswerCeleryTask.CHECK_TTL_MANAGEMENT_TASK,
        "schedule": timedelta(hours=1),
    },
]


def get_tasks_to_schedule() -> list[dict[str, Any]]:
    return ee_tasks_to_schedule + base_tasks_to_schedule
