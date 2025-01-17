from datetime import timedelta
from typing import Any
from typing import cast

from celery import Celery
from celery import signals
from celery.beat import PersistentScheduler  # type: ignore
from celery.signals import beat_init

import onyx.background.celery.apps.app_base as app_base
from onyx.configs.constants import ONYX_CLOUD_CELERY_TASK_PREFIX
from onyx.configs.constants import POSTGRES_CELERY_BEAT_APP_NAME
from onyx.db.engine import get_all_tenant_ids
from onyx.db.engine import SqlEngine
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import IGNORED_SYNCING_TENANT_LIST
from shared_configs.configs import MULTI_TENANT

logger = setup_logger(__name__)

celery_app = Celery(__name__)
celery_app.config_from_object("onyx.background.celery.configs.beat")


class DynamicTenantScheduler(PersistentScheduler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        logger.info("Initializing DynamicTenantScheduler")
        super().__init__(*args, **kwargs)
        self._reload_interval = timedelta(minutes=2)
        self._last_reload = self.app.now() - self._reload_interval
        # Let the parent class handle store initialization
        self.setup_schedule()
        self._try_updating_schedule()
        logger.info(f"Set reload interval to {self._reload_interval}")

    def setup_schedule(self) -> None:
        logger.info("Setting up initial schedule")
        super().setup_schedule()
        logger.info("Initial schedule setup complete")

    def tick(self) -> float:
        retval = super().tick()
        now = self.app.now()
        if (
            self._last_reload is None
            or (now - self._last_reload) > self._reload_interval
        ):
            logger.info("Reload interval reached, initiating task update")
            try:
                self._try_updating_schedule()
            except (AttributeError, KeyError) as e:
                logger.exception(f"Failed to process task configuration: {str(e)}")
            except Exception as e:
                logger.exception(f"Unexpected error updating tasks: {str(e)}")

            self._last_reload = now
            logger.info("Task update completed, reset reload timer")
        return retval

    def _generate_schedule(
        self, tenant_ids: list[str] | list[None]
    ) -> dict[str, dict[str, Any]]:
        """Given a list of tenant id's, generates a new beat schedule for celery."""
        logger.info("Fetching tasks to schedule")

        new_schedule: dict[str, dict[str, Any]] = {}

        if MULTI_TENANT:
            # cloud tasks only need the single task beat across all tenants
            get_cloud_tasks_to_schedule = fetch_versioned_implementation(
                "onyx.background.celery.tasks.beat_schedule",
                "get_cloud_tasks_to_schedule",
            )

            cloud_tasks_to_schedule: list[
                dict[str, Any]
            ] = get_cloud_tasks_to_schedule()
            for task in cloud_tasks_to_schedule:
                task_name = task["name"]
                cloud_task = {
                    "task": task["task"],
                    "schedule": task["schedule"],
                    "kwargs": {},
                }
                if options := task.get("options"):
                    logger.debug(f"Adding options to task {task_name}: {options}")
                    cloud_task["options"] = options
                new_schedule[task_name] = cloud_task

        # regular task beats are multiplied across all tenants
        get_tasks_to_schedule = fetch_versioned_implementation(
            "onyx.background.celery.tasks.beat_schedule", "get_tasks_to_schedule"
        )

        tasks_to_schedule: list[dict[str, Any]] = get_tasks_to_schedule()

        for tenant_id in tenant_ids:
            if IGNORED_SYNCING_TENANT_LIST and tenant_id in IGNORED_SYNCING_TENANT_LIST:
                logger.info(
                    f"Skipping tenant {tenant_id} as it is in the ignored syncing list"
                )
                continue

            for task in tasks_to_schedule:
                task_name = task["name"]
                tenant_task_name = f"{task['name']}-{tenant_id}"

                logger.debug(f"Creating task configuration for {tenant_task_name}")
                tenant_task = {
                    "task": task["task"],
                    "schedule": task["schedule"],
                    "kwargs": {"tenant_id": tenant_id},
                }
                if options := task.get("options"):
                    logger.debug(
                        f"Adding options to task {tenant_task_name}: {options}"
                    )
                    tenant_task["options"] = options
                new_schedule[tenant_task_name] = tenant_task

        return new_schedule

    def _try_updating_schedule(self) -> None:
        """Only updates the actual beat schedule on the celery app when it changes"""

        logger.info("_try_updating_schedule starting")

        tenant_ids = get_all_tenant_ids()
        logger.info(f"Found {len(tenant_ids)} IDs")

        # get current schedule and extract current tenants
        current_schedule = self.schedule.items()

        current_tenants = set()
        for task_name, _ in current_schedule:
            task_name = cast(str, task_name)
            if task_name.startswith(ONYX_CLOUD_CELERY_TASK_PREFIX):
                continue

            if "_" in task_name:
                # example: "check-for-condition-tenant_12345678-abcd-efgh-ijkl-12345678"
                # -> "12345678-abcd-efgh-ijkl-12345678"
                current_tenants.add(task_name.split("_")[-1])
        logger.info(f"Found {len(current_tenants)} existing items in schedule")

        for tenant_id in tenant_ids:
            if tenant_id not in current_tenants:
                logger.info(f"Processing new tenant: {tenant_id}")

        new_schedule = self._generate_schedule(tenant_ids)

        if DynamicTenantScheduler._compare_schedules(current_schedule, new_schedule):
            logger.info(
                "_try_updating_schedule: Current schedule is up to date, no changes needed"
            )
            return

        logger.info(
            "Schedule update required",
            extra={
                "new_tasks": len(new_schedule),
                "current_tasks": len(current_schedule),
            },
        )

        # Create schedule entries
        entries = {}
        for name, entry in new_schedule.items():
            entries[name] = self.Entry(
                name=name,
                app=self.app,
                task=entry["task"],
                schedule=entry["schedule"],
                options=entry.get("options", {}),
                kwargs=entry.get("kwargs", {}),
            )

        # Update the schedule using the scheduler's methods
        self.schedule.clear()
        self.schedule.update(entries)

        # Ensure changes are persisted
        self.sync()

        logger.info("_try_updating_schedule: Schedule updated successfully")

    @staticmethod
    def _compare_schedules(schedule1: dict, schedule2: dict) -> bool:
        """Compare schedules to determine if an update is needed.
        True if equivalent, False if not."""
        current_tasks = set(name for name, _ in schedule1)
        new_tasks = set(schedule2.keys())
        if current_tasks != new_tasks:
            return False

        return True


@beat_init.connect
def on_beat_init(sender: Any, **kwargs: Any) -> None:
    logger.info("beat_init signal received.")

    # Celery beat shouldn't touch the db at all. But just setting a low minimum here.
    SqlEngine.set_app_name(POSTGRES_CELERY_BEAT_APP_NAME)
    SqlEngine.init_engine(pool_size=2, max_overflow=0)

    app_base.wait_for_redis(sender, **kwargs)


@signals.setup_logging.connect
def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    app_base.on_setup_logging(loglevel, logfile, format, colorize, **kwargs)


celery_app.conf.beat_scheduler = DynamicTenantScheduler
