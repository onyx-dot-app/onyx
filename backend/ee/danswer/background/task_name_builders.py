def name_user_group_sync_task(user_group_id: int) -> str:
    return f"user_group_sync_task__{user_group_id}"


def name_chat_ttl_task(retention_limit_days: int) -> str:
    return f"chat_ttl_{retention_limit_days}_days"
