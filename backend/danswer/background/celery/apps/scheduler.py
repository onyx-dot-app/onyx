from datetime import timedelta
from typing import Any

from celery.beat import PersistentScheduler  # type: ignore
from celery.utils.log import get_task_logger

from danswer.db.engine import get_all_tenant_ids
from danswer.utils.variable_functionality import fetch_versioned_implementation

logger = get_task_logger(__name__)


class DynamicTenantScheduler(PersistentScheduler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._reload_interval = timedelta(minutes=1)
        self._last_reload = self.app.now() - self._reload_interval

    def setup_schedule(self) -> None:
        super().setup_schedule()

    def tick(self) -> float:
        retval = super().tick()
        now = self.app.now()
        if (
            self._last_reload is None
            or (now - self._last_reload) > self._reload_interval
        ):
            logger.info("Reloading schedule to check for new tenants...")
            self._update_tenant_tasks()
            self._last_reload = now
        return retval

    def _update_tenant_tasks(self) -> None:
        logger.info("Checking for tenant task updates...")
        try:
            tenant_ids = get_all_tenant_ids()
            tasks_to_schedule = fetch_versioned_implementation(
                "danswer.background.celery.tasks.beat_schedule", "get_tasks_to_schedule"
            )

            new_beat_schedule: dict[str, dict[str, Any]] = {}

            current_schedule = getattr(self, "_store", {"entries": {}}).get(
                "entries", {}
            )

            existing_tenants = set()
            for task_name in current_schedule.keys():
                if "-" in task_name:
                    existing_tenants.add(task_name.split("-")[-1])

            for tenant_id in tenant_ids:
                if tenant_id not in existing_tenants:
                    logger.info(f"Found new tenant: {tenant_id}")

                for task in tasks_to_schedule():
                    task_name = f"{task['name']}-{tenant_id}"
                    new_task = {
                        "task": task["task"],
                        "schedule": task["schedule"],
                        "kwargs": {"tenant_id": tenant_id},
                    }
                    if options := task.get("options"):
                        new_task["options"] = options
                    new_beat_schedule[task_name] = new_task

            if self._should_update_schedule(current_schedule, new_beat_schedule):
                logger.info(
                    "Updating schedule",
                    extra={
                        "new_tasks": len(new_beat_schedule),
                        "current_tasks": len(current_schedule),
                    },
                )
                if not hasattr(self, "_store"):
                    self._store: dict[str, dict] = {"entries": {}}
                self.update_from_dict(new_beat_schedule)
                logger.info(f"New schedule: {new_beat_schedule}")

                logger.info("Tenant tasks updated successfully")
            else:
                logger.debug("No schedule updates needed")

        except (AttributeError, KeyError):
            logger.exception("Failed to process task configuration")
        except Exception:
            logger.exception("Unexpected error updating tenant tasks")

    def _should_update_schedule(
        self, current_schedule: dict, new_schedule: dict
    ) -> bool:
        """Compare schedules to determine if an update is needed."""
        current_tasks = set(current_schedule.keys())
        new_tasks = set(new_schedule.keys())
        return current_tasks != new_tasks
