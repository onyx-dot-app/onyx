"""Guards the Celery wiring of the one-time credential import: beat schedules
the task on the primary queue, the primary worker reads that queue and registers the
task. A missing piece fails with no error at run time."""

from onyx.background.celery.tasks.beat_schedule import beat_task_templates
from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask
from tests.unit.onyx.background.celery.tasks.test_port_wiring import _worker_queues


def test_import_task_scheduled_on_its_queue() -> None:
    entries = [
        entry
        for entry in beat_task_templates
        if entry["task"] == OnyxCeleryTask.IMPORT_INTEGRATION_CREDENTIALS
    ]
    assert len(entries) == 1
    options = entries[0]["options"]
    assert options["queue"] == OnyxCeleryQueues.PRIMARY
    assert options["expires"] > 0


def test_primary_worker_consumes_import_queue() -> None:
    assert OnyxCeleryQueues.PRIMARY in _worker_queues("celery_worker_primary")


def test_primary_worker_registers_import_task() -> None:
    from onyx.background.celery.apps.primary import celery_app

    celery_app.loader.import_default_modules()
    assert OnyxCeleryTask.IMPORT_INTEGRATION_CREDENTIALS in set(celery_app.tasks)
