from unittest.mock import MagicMock, patch

from onyx.background.celery.tasks.docprocessing.tasks import _docprocessing_task

MODULE = "onyx.background.celery.tasks.docprocessing.tasks"


def test_empty_batch_records_completion() -> None:
    """A batch whose documents were all dropped at deserialization must still
    count toward completed_batches — a bare return would stall the attempt."""
    storage = MagicMock()
    storage.get_batch.return_value = []

    with (
        patch(f"{MODULE}.USAGE_LIMITS_ENABLED", False),
        patch(f"{MODULE}.MANAGED_VESPA", False),
        patch(f"{MODULE}.httpx_init_vespa_pool"),
        patch(f"{MODULE}.get_document_batch_storage", return_value=storage),
        patch(f"{MODULE}.RedisConnector"),
        patch(f"{MODULE}.get_redis_client"),
        patch(f"{MODULE}.emit_process_memory"),
        patch(f"{MODULE}.safe_record_single_event"),
        patch(f"{MODULE}.get_session_with_current_tenant"),
        patch(f"{MODULE}.IndexingCoordination") as coordination,
    ):
        _docprocessing_task(
            index_attempt_id=7,
            cc_pair_id=3,
            tenant_id="public",
            batch_num=2,
        )

    storage.get_batch.assert_called_once_with(2)
    coordination.update_batch_completion_and_docs.assert_called_once()
    kwargs = coordination.update_batch_completion_and_docs.call_args.kwargs
    assert kwargs["index_attempt_id"] == 7
    assert kwargs["total_docs_indexed"] == 0
    assert kwargs["new_docs_indexed"] == 0
    assert kwargs["total_chunks"] == 0
