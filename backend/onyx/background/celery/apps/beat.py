from datetime import timedelta
from typing import Any

from celery import Celery
from celery import signals
from celery.beat import PersistentScheduler  # type: ignore
from celery.signals import beat_init
from celery.utils.log import get_task_logger

import onyx.background.celery.apps.app_base as app_base
from onyx.background.celery.celery_utils import make_probe_path
from onyx.background.celery.tasks.beat_schedule import CLOUD_BEAT_MULTIPLIER_DEFAULT
from onyx.configs.constants import POSTGRES_CELERY_BEAT_APP_NAME
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.tenant_utils import get_all_tenant_ids
from onyx.server.runtime.onyx_runtime import OnyxRuntime
from onyx.utils.variable_functionality import fetch_versioned_implementation
from shared_configs.configs import IGNORED_SYNCING_TENANT_LIST
from shared_configs.configs import MULTI_TENANT

task_logger = get_task_logger(__name__)

celery_app = Celery(__name__)
celery_app.config_from_object("onyx.background.celery.configs.beat")


class DynamicTenantScheduler(PersistentScheduler):
    """This scheduler is useful because we can dynamically adjust task generation rates
    through it."""

    RELOAD_INTERVAL = 60

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.last_beat_multiplier = CLOUD_BEAT_MULTIPLIER_DEFAULT

        self._reload_interval = timedelta(
            seconds=DynamicTenantScheduler.RELOAD_INTERVAL
        )
        self._last_reload = self.app.now() - self._reload_interval

        # Let the parent class handle store initialization
        self.setup_schedule()
        task_logger.info(
            f"DynamicTenantScheduler initialized: reload_interval={self._reload_interval}"
        )

        self._liveness_probe_path = make_probe_path("liveness", "beat@hostname")

        # do not set the initial schedule here because we don't have db access yet.
        # do it in beat_init after the db engine is initialized

        # An initial schedule is required ... otherwise, the scheduler will delay
        # for 5 minutes before calling tick()

    def setup_schedule(self) -> None:
        super().setup_schedule()

    def tick(self) -> float:
        retval = super().tick()
        now = self.app.now()
        if (
            self._last_reload is None
            or (now - self._last_reload) > self._reload_interval
        ):
            task_logger.debug("Reload interval reached, initiating task update")
            self._liveness_probe_path.touch()

            try:
                self._try_updating_schedule()
            except (AttributeError, KeyError):
                task_logger.exception("Failed to process task configuration")
            except Exception:
                task_logger.exception("Unexpected error updating tasks")

            self._last_reload = now

        return retval

    def _generate_schedule(
        self, tenant_ids: list[str] | list[None], beat_multiplier: float
    ) -> dict[str, dict[str, Any]]:
        """Given a list of tenant id's, generates a new beat schedule for celery."""
        new_schedule: dict[str, dict[str, Any]] = {}

        if MULTI_TENANT:
            # cloud tasks are system wide and thus only need to be on the beat schedule
            # once for all tenants
            get_cloud_tasks_to_schedule = fetch_versioned_implementation(
                "onyx.background.celery.tasks.beat_schedule",
                "get_cloud_tasks_to_schedule",
            )

            cloud_tasks_to_schedule: list[dict[str, Any]] = get_cloud_tasks_to_schedule(
                beat_multiplier
            )
            for task in cloud_tasks_to_schedule:
                task_name = task["name"]
                cloud_task = {
                    "task": task["task"],
                    "schedule": task["schedule"],
                    "kwargs": task.get("kwargs", {}),
                }
                if options := task.get("options"):
                    task_logger.debug(f"Adding options to task {task_name}: {options}")
                    cloud_task["options"] = options
                new_schedule[task_name] = cloud_task

        # regular task beats are multiplied across all tenants
        # note that currently this just schedules for a single tenant in self hosted
        # and doesn't do anything in the cloud because it's much more scalable
        # to schedule a single cloud beat task to dispatch per tenant tasks.
        get_tasks_to_schedule = fetch_versioned_implementation(
            "onyx.background.celery.tasks.beat_schedule", "get_tasks_to_schedule"
        )

        tasks_to_schedule: list[dict[str, Any]] = get_tasks_to_schedule()

        for tenant_id in tenant_ids:
            if IGNORED_SYNCING_TENANT_LIST and tenant_id in IGNORED_SYNCING_TENANT_LIST:
                task_logger.debug(
                    f"Skipping tenant {tenant_id} as it is in the ignored syncing list"
                )
                continue

            for task in tasks_to_schedule:
                task_name = task["name"]
                tenant_task_name = f"{task['name']}-{tenant_id}"

                task_logger.debug(f"Creating task configuration for {tenant_task_name}")
                tenant_task = {
                    "task": task["task"],
                    "schedule": task["schedule"],
                    "kwargs": {"tenant_id": tenant_id},
                }
                if options := task.get("options"):
                    task_logger.debug(
                        f"Adding options to task {tenant_task_name}: {options}"
                    )
                    tenant_task["options"] = options

                new_schedule[tenant_task_name] = tenant_task

        return new_schedule

    def _try_updating_schedule(self) -> None:
        """Only updates the actual beat schedule on the celery app when it changes"""
        do_update = False

        task_logger.debug("_try_updating_schedule starting")

        tenant_ids = get_all_tenant_ids()
        task_logger.debug(f"Found {len(tenant_ids)} IDs")

        # get current schedule and extract current tenants
        current_schedule = self.schedule.items()

        # get potential new state
        try:
            beat_multiplier = OnyxRuntime.get_beat_multiplier()
        except Exception:
            beat_multiplier = CLOUD_BEAT_MULTIPLIER_DEFAULT

        new_schedule = self._generate_schedule(tenant_ids, beat_multiplier)

        # if the schedule or beat multiplier has changed, update
        while True:
            if beat_multiplier != self.last_beat_multiplier:
                do_update = True
                break

            if not DynamicTenantScheduler._compare_schedules(
                current_schedule, new_schedule
            ):
                do_update = True
                break

            break

        if not do_update:
            # exit early if nothing changed
            task_logger.info(
                f"_try_updating_schedule - Schedule unchanged: "
                f"tasks={len(new_schedule)} "
                f"beat_multiplier={beat_multiplier}"
            )
            return

        # schedule needs updating
        task_logger.debug(
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

        task_logger.info(
            f"_try_updating_schedule - Schedule updated: "
            f"prev_num_tasks={len(current_schedule)} "
            f"prev_beat_multiplier={self.last_beat_multiplier} "
            f"tasks={len(new_schedule)} "
            f"beat_multiplier={beat_multiplier}"
        )

        self.last_beat_multiplier = beat_multiplier

    @staticmethod
    def _compare_schedules(schedule1: dict, schedule2: dict) -> bool:
        """Compare schedules by task name only to determine if an update is needed.
        True if equivalent, False if not."""
        current_tasks = set(name for name, _ in schedule1)
        new_tasks = set(schedule2.keys())
        return current_tasks == new_tasks


@beat_init.connect
def on_beat_init(sender: Any, **kwargs: Any) -> None:
    task_logger.info("beat_init signal received.")

    # Celery beat shouldn't touch the db at all. But just setting a low minimum here.
    SqlEngine.set_app_name(POSTGRES_CELERY_BEAT_APP_NAME)
    SqlEngine.init_engine(pool_size=2, max_overflow=0)

    app_base.wait_for_redis(sender, **kwargs)
    path = make_probe_path("readiness", "beat@hostname")
    path.touch()
    task_logger.info(f"Readiness signal touched at {path}.")

    # first time init of the scheduler after db has been init'ed
    scheduler: DynamicTenantScheduler = sender.scheduler
    scheduler._try_updating_schedule()


@signals.setup_logging.connect
def on_setup_logging(
    loglevel: Any, logfile: Any, format: Any, colorize: Any, **kwargs: Any
) -> None:
    app_base.on_setup_logging(loglevel, logfile, format, colorize, **kwargs)


celery_app.conf.beat_scheduler = DynamicTenantScheduler
celery_app.conf.task_default_base = app_base.TenantAwareTask
