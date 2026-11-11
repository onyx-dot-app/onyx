from onyx.background.celery.apps.docprocessing import celery_app
from onyx.configs.constants import OnyxCeleryTask


def test_docprocessing_task_acks_on_receipt_in_its_worker() -> None:
    """The worker config acks late by default. With acks_late, the broker
    redelivers a batch that outlives the visibility timeout while its first
    worker still runs it, and the duplicate completion can end the attempt
    before its other batches are indexed."""
    celery_app.loader.import_default_modules()

    assert celery_app.conf.task_acks_late is True
    assert celery_app.tasks[OnyxCeleryTask.DOCPROCESSING_TASK].acks_late is False
