def name_chat_ttl_task(retention_limit_days: int, tenant_id: str | None = None) -> str:
    return f"chat_ttl_{retention_limit_days}_days"
