from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.background.celery.tasks.user_file_processing.tasks import (
    _user_file_project_sync_queued_key,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    check_for_user_file_project_sync,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    enqueue_user_file_project_sync_task,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    process_single_user_file_project_sync,
)
from onyx.configs.constants import CELERY_USER_FILE_PROJECT_SYNC_TASK_EXPIRES
from onyx.configs.constants import OnyxCeleryPriority
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import USER_FILE_PROJECT_SYNC_MAX_QUEUE_DEPTH


def _build_redis_mock_with_lock() -> tuple[MagicMock, MagicMock]:
    redis_client = MagicMock()
    lock = MagicMock()
    lock.acquire.return_value = True
    lock.owned.return_value = True
    redis_client.lock.return_value = lock
    return redis_client, lock


@patch(
    "onyx.background.celery.tasks.user_file_processing.tasks."
    "get_user_file_project_sync_queue_depth"
)
@patch("onyx.background.celery.tasks.user_file_processing.tasks.get_redis_client")
def test_check_for_user_file_project_sync_applies_queue_backpressure(
    mock_get_redis_client: MagicMock,
    mock_get_queue_depth: MagicMock,
) -> None:
    redis_client, lock = _build_redis_mock_with_lock()
    mock_get_redis_client.return_value = redis_client
    mock_get_queue_depth.return_value = USER_FILE_PROJECT_SYNC_MAX_QUEUE_DEPTH + 1

    task_app = MagicMock()
    with patch.object(check_for_user_file_project_sync, "app", task_app):
        check_for_user_file_project_sync.run(tenant_id="test-tenant")

    task_app.send_task.assert_not_called()
    lock.release.assert_called_once()


@patch(
    "onyx.background.celery.tasks.user_file_processing.tasks."
    "enqueue_user_file_project_sync_task"
)
@patch(
    "onyx.background.celery.tasks.user_file_processing.tasks."
    "get_user_file_project_sync_queue_depth"
)
@patch(
    "onyx.background.celery.tasks.user_file_processing.tasks."
    "get_session_with_current_tenant"
)
@patch("onyx.background.celery.tasks.user_file_processing.tasks.get_redis_client")
def test_check_for_user_file_project_sync_skips_duplicates(
    mock_get_redis_client: MagicMock,
    mock_get_session: MagicMock,
    mock_get_queue_depth: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    redis_client, lock = _build_redis_mock_with_lock()
    mock_get_redis_client.return_value = redis_client
    mock_get_queue_depth.return_value = 0

    user_file_id_one = uuid4()
    user_file_id_two = uuid4()

    session = MagicMock()
    session.execute.return_value.scalars.return_value.all.return_value = [
        user_file_id_one,
        user_file_id_two,
    ]
    mock_get_session.return_value.__enter__.return_value = session
    mock_enqueue.side_effect = [True, False]

    task_app = MagicMock()
    with patch.object(check_for_user_file_project_sync, "app", task_app):
        check_for_user_file_project_sync.run(tenant_id="test-tenant")

    assert mock_enqueue.call_count == 2
    lock.release.assert_called_once()


def test_enqueue_user_file_project_sync_task_sets_guard_and_expiry() -> None:
    redis_client = MagicMock()
    redis_client.set.return_value = True
    celery_app = MagicMock()
    user_file_id = str(uuid4())

    enqueued = enqueue_user_file_project_sync_task(
        celery_app=celery_app,
        redis_client=redis_client,
        user_file_id=user_file_id,
        tenant_id="test-tenant",
        priority=OnyxCeleryPriority.HIGHEST,
    )

    assert enqueued is True
    redis_client.set.assert_called_once_with(
        _user_file_project_sync_queued_key(user_file_id),
        1,
        nx=True,
        ex=CELERY_USER_FILE_PROJECT_SYNC_TASK_EXPIRES,
    )
    celery_app.send_task.assert_called_once_with(
        OnyxCeleryTask.PROCESS_SINGLE_USER_FILE_PROJECT_SYNC,
        kwargs={"user_file_id": user_file_id, "tenant_id": "test-tenant"},
        queue=OnyxCeleryQueues.USER_FILE_PROJECT_SYNC,
        priority=OnyxCeleryPriority.HIGHEST,
        expires=CELERY_USER_FILE_PROJECT_SYNC_TASK_EXPIRES,
    )


def test_enqueue_user_file_project_sync_task_rolls_back_guard_on_publish_failure() -> (
    None
):
    redis_client = MagicMock()
    redis_client.set.return_value = True
    celery_app = MagicMock()
    celery_app.send_task.side_effect = RuntimeError("publish failed")

    user_file_id = str(uuid4())
    with pytest.raises(RuntimeError):
        enqueue_user_file_project_sync_task(
            celery_app=celery_app,
            redis_client=redis_client,
            user_file_id=user_file_id,
            tenant_id="test-tenant",
        )

    redis_client.delete.assert_called_once_with(
        _user_file_project_sync_queued_key(user_file_id)
    )


@patch("onyx.background.celery.tasks.user_file_processing.tasks.get_redis_client")
def test_process_single_user_file_project_sync_clears_queued_guard_on_pickup(
    mock_get_redis_client: MagicMock,
) -> None:
    redis_client = MagicMock()
    lock = MagicMock()
    lock.acquire.return_value = False
    redis_client.lock.return_value = lock
    mock_get_redis_client.return_value = redis_client

    user_file_id = str(uuid4())
    process_single_user_file_project_sync.run(
        user_file_id=user_file_id,
        tenant_id="test-tenant",
    )

    redis_client.delete.assert_called_once_with(
        _user_file_project_sync_queued_key(user_file_id)
    )
