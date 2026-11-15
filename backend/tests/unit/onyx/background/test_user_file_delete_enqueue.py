"""Guards that queued user file deletes reach a consumer on every deployment.

Lite deployments run no Celery, so a send_task there lands on a queue nothing
drains and the delete waits on the recovery poll instead of running with the
request.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import BackgroundTasks

from onyx.background.task_utils import drain_delete_loop, enqueue_user_file_deletes

MODULE = "onyx.background.task_utils"
TENANT = "tenant_test"


def _enqueue(file_count: int, lite: bool) -> tuple[MagicMock, BackgroundTasks]:
    """Returns the celery client the call would have used, and the request's
    background tasks."""
    client = MagicMock()
    bg_tasks = BackgroundTasks()
    file_ids = [uuid4() for _ in range(file_count)]
    with (
        patch(f"{MODULE}.DISABLE_VECTOR_DB", lite),
        patch.dict(
            "sys.modules",
            {"onyx.background.celery.versioned_apps.client": MagicMock(app=client)},
        ),
    ):
        enqueue_user_file_deletes(file_ids, tenant_id=TENANT, bg_tasks=bg_tasks)
    return client, bg_tasks


def test_lite_deployment_drains_in_process_instead_of_queueing() -> None:
    client, bg_tasks = _enqueue(file_count=2, lite=True)

    client.send_task.assert_not_called()
    assert [task.func for task in bg_tasks.tasks] == [drain_delete_loop]
    assert bg_tasks.tasks[0].args == (TENANT,)


def test_ordinary_deployment_sends_one_expiring_task_per_file() -> None:
    """A delete task with no expiry sits on the queue forever when nothing
    drains it."""
    client, bg_tasks = _enqueue(file_count=3, lite=False)

    assert client.send_task.call_count == 3
    assert client.send_task.call_args.kwargs["expires"]
    assert bg_tasks.tasks == []
