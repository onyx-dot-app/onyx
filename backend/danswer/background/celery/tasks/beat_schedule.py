from datetime import timedelta
from typing import Any

from danswer.configs.constants import DanswerCeleryPriority
from danswer.configs.constants import DanswerCeleryTask


tasks_to_schedule = [
    {
        "name": "check-for-vespa-sync",
        "task": DanswerCeleryTask.CHECK_FOR_VESPA_SYNC_TASK,
        "schedule": timedelta(seconds=20),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-connector-deletion",
        "task": DanswerCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
        "schedule": timedelta(seconds=20),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-indexing",
        "task": DanswerCeleryTask.CHECK_FOR_INDEXING,
        "schedule": timedelta(seconds=15),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-prune",
        "task": DanswerCeleryTask.CHECK_FOR_PRUNING,
        "schedule": timedelta(seconds=15),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "kombu-message-cleanup",
        "task": DanswerCeleryTask.KOMBU_MESSAGE_CLEANUP_TASK,
        "schedule": timedelta(seconds=3600),
        "options": {"priority": DanswerCeleryPriority.LOWEST},
    },
    {
        "name": "monitor-vespa-sync",
        "task": DanswerCeleryTask.MONITOR_VESPA_SYNC,
        "schedule": timedelta(seconds=5),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-doc-permissions-sync",
        "task": DanswerCeleryTask.CHECK_FOR_DOC_PERMISSIONS_SYNC,
        "schedule": timedelta(seconds=30),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
    {
        "name": "check-for-external-group-sync",
        "task": DanswerCeleryTask.CHECK_FOR_EXTERNAL_GROUP_SYNC,
        "schedule": timedelta(seconds=20),
        "options": {"priority": DanswerCeleryPriority.HIGH},
    },
]


def get_tasks_to_schedule() -> list[dict[str, Any]]:
    return tasks_to_schedule
