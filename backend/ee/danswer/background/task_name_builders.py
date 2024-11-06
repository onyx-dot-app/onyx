def name_chat_ttl_task(retention_limit_days: int, tenant_id: str | None = None) -> str:
    return f"chat_ttl_{retention_limit_days}_days"


def name_sync_external_doc_permissions_task(
    cc_pair_id: int, tenant_id: str | None = None
) -> str:
    return f"sync_external_doc_permissions_task__{cc_pair_id}"


def name_sync_external_group_permissions_task(
    cc_pair_id: int, tenant_id: str | None = None
) -> str:
    return f"sync_external_group_permissions_task__{cc_pair_id}"
