from datetime import datetime

from onyx.configs.constants import OnyxCeleryTask


QUERY_HISTORY_TASK_NAME_PREFIX = OnyxCeleryTask.EXPORT_QUERY_HISTORY_TASK


def name_chat_ttl_task(
    retention_limit_days: float, tenant_id: str | None = None
) -> str:
    return f"chat_ttl_{retention_limit_days}_days"


def query_history_task_name(start: datetime, end: datetime) -> str:
    return f"{QUERY_HISTORY_TASK_NAME_PREFIX}_{start}_{end}"
