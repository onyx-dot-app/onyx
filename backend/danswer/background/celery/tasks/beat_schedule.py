from datetime import timedelta
from typing import Any

from danswer.configs.constants import DanswerCeleryPriority


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
        "schedule": timedelta(seconds=20),
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


def get_tasks_to_schedule() -> list[dict[str, Any]]:
    return tasks_to_schedule
