from celery import Task, shared_task

from onyx.background.celery.tasks.docprocessing.heartbeat import (
    start_heartbeat,
    stop_heartbeat,
)
from onyx.background.indexing.run_docconversion import convert_stub_batch
from onyx.background.indexing.run_docfetching import mark_attempt_failed_unless_terminal
from onyx.configs.constants import OnyxCeleryTask
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    INDEX_ATTEMPT_INFO_CONTEXTVAR,
)


# Acknowledged on receipt, like docprocessing. With acks_late, the broker
# redelivers a task that runs past visibility_timeout while the first worker
# still converts it. A batch lost to a worker crash stays in the stub batch
# store, so it can be sent again.
@shared_task(  # ty: ignore[invalid-argument-type]
    name=OnyxCeleryTask.DOCCONVERSION_TASK,
    bind=True,
    acks_late=False,
)
def docconversion_task(
    self: Task,
    index_attempt_id: int,
    cc_pair_id: int,
    tenant_id: str,
    batch_num: int,
    enqueue_time_ms: int | None = None,
    is_backfill: bool = False,
) -> None:
    """Converts one stub batch of an index attempt: fetches and parses its
    listed documents, stores them as a document batch, and sends that batch
    to docprocessing. Then it sends the next stub batches of the attempt."""
    heartbeat_thread, stop_event = start_heartbeat(index_attempt_id)
    token = INDEX_ATTEMPT_INFO_CONTEXTVAR.set((cc_pair_id, index_attempt_id))
    try:
        if tenant_id:
            CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        convert_stub_batch(
            self.app,
            index_attempt_id=index_attempt_id,
            cc_pair_id=cc_pair_id,
            tenant_id=tenant_id,
            batch_num=batch_num,
            enqueue_time_ms=enqueue_time_ms,
            is_backfill=is_backfill,
            task_id=self.request.id,
        )
    except Exception as e:
        # Nothing sends the batch again after a failure that repeats, so the
        # attempt fails here, as it does when docfetching raises.
        mark_attempt_failed_unless_terminal(index_attempt_id, e)
        raise
    finally:
        stop_heartbeat(heartbeat_thread, stop_event)
        INDEX_ATTEMPT_INFO_CONTEXTVAR.reset(token)
