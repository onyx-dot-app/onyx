#####
# Celery Beat (Periodic Tasks) Settings
#####
from datetime import timedelta

from danswer.background.celery.apps.beat import celery_app
from danswer.db.engine import get_all_tenant_ids


tenant_ids = get_all_tenant_ids()

tasks_to_schedule = [
    {
        "name": "sync-external-doc-permissions",
        "task": "check_sync_external_doc_permissions_task",
        "schedule": timedelta(seconds=5),  # TODO: optimize this
    },
    {
        "name": "sync-external-group-permissions",
        "task": "check_sync_external_group_permissions_task",
        "schedule": timedelta(seconds=5),  # TODO: optimize this
    },
    {
        "name": "autogenerate_usage_report",
        "task": "autogenerate_usage_report_task",
        "schedule": timedelta(days=30),  # TODO: change this to config flag
    },
    {
        "name": "check-ttl-management",
        "task": "check_ttl_management_task",
        "schedule": timedelta(hours=1),
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
            "kwargs": {"tenant_id": tenant_id},  # Must pass tenant_id as an argument
        }

# Include any existing beat schedules
existing_beat_schedule = celery_app.conf.beat_schedule or {}
beat_schedule.update(existing_beat_schedule)

# Update the Celery app configuration
celery_app.conf.beat_schedule = beat_schedule
