def name_sync_external_doc_permissions_task(
    cc_pair_id: int, tenant_id: str | None = None
) -> str:
    return f"sync_external_doc_permissions_task__{cc_pair_id}"
