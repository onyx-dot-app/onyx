from datetime import timedelta
from typing import Any

from onyx.background.celery.apps.beat import DynamicTenantScheduler
from onyx.configs.constants import OnyxCeleryTask


class ConnectorTestScheduler(DynamicTenantScheduler):
    def _generate_schedule(
        self, tenant_ids: list[str] | list[None], beat_multiplier: float
    ) -> dict[str, dict[str, Any]]:
        schedule = super()._generate_schedule(tenant_ids, beat_multiplier)
        for entry in schedule.values():
            if entry["task"] in {
                OnyxCeleryTask.CHECK_FOR_INDEXING,
                OnyxCeleryTask.CHECK_FOR_CONNECTOR_DELETION,
                OnyxCeleryTask.CHECK_FOR_VESPA_SYNC_TASK,
                OnyxCeleryTask.CHECK_FOR_DOC_PERMISSIONS_SYNC,
                OnyxCeleryTask.CHECK_FOR_EXTERNAL_GROUP_SYNC,
            }:
                entry["schedule"] = timedelta(seconds=5)
        return schedule
