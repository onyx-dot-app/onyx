from datetime import datetime


def name_chat_ttl_task(retention_limit_days: int, tenant_id: str | None = None) -> str:
    return f"chat_ttl_{retention_limit_days}_days"


def name_query_history_report_task(start: datetime, end: datetime) -> str:
    start_epoch = int(start.timestamp())
    end_epoch = int(end.timestamp())
    return f"query_history_report_{start_epoch}_{end_epoch}"
