"""
External dependency unit tests for user file processing queue protections.

Verifies that the three mechanisms added to check_user_file_processing work
correctly:

1. Queue depth backpressure – when the broker queue exceeds
   USER_FILE_PROCESSING_MAX_QUEUE_DEPTH, no new tasks are enqueued.

2. Per-file Redis guard key – if the guard key for a file already exists in
   Redis, that file is skipped even though it is still in PROCESSING status.

3. Task expiry – every send_task call carries expires=
   CELERY_USER_FILE_PROCESSING_TASK_EXPIRES so that stale queued tasks are
   discarded by workers automatically.

Also verifies that process_single_user_file clears the guard key the moment
it is picked up by a worker.

Uses real Redis (DB 0 via get_redis_client) and real PostgreSQL for UserFile
rows.  The Celery app is provided as a MagicMock so no real broker is needed.
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.background.celery.tasks.user_file_processing.tasks import (
    _user_file_lock_key,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _user_file_queued_key,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    check_user_file_processing,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    process_single_user_file,
)
from onyx.configs.constants import CELERY_USER_FILE_PROCESSING_TASK_EXPIRES
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.configs.constants import USER_FILE_PROCESSING_MAX_QUEUE_DEPTH
from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.constants import TEST_TENANT_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PATCH_QUEUE_LEN = (
    "onyx.background.celery.tasks.user_file_processing.tasks.celery_get_queue_length"
)


def _create_processing_user_file(db_session: Session, user_id: object) -> UserFile:
    """Insert a UserFile in PROCESSING status and return it."""
    uf = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id=f"test_file_{uuid4().hex[:8]}",
        name=f"test_{uuid4().hex[:8]}.txt",
        file_type="text/plain",
        status=UserFileStatus.PROCESSING,
    )
    db_session.add(uf)
    db_session.commit()
    db_session.refresh(uf)
    return uf


def _mock_self() -> MagicMock:
    """Return a MagicMock that acts as the bound Celery Task instance.

    celery_get_queue_length is patched in each test, so the broker connection
    only needs to return *something* without raising.
    """
    return MagicMock()


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestQueueDepthBackpressure:
    """Protection 1: skip all enqueuing when the broker queue is too deep."""

    def test_no_tasks_enqueued_when_queue_over_limit(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """When the queue depth exceeds the limit the beat cycle is skipped."""
        user = create_test_user(db_session, "bp_user")
        _create_processing_user_file(db_session, user.id)

        mock_task = _mock_self()

        with patch(
            _PATCH_QUEUE_LEN, return_value=USER_FILE_PROCESSING_MAX_QUEUE_DEPTH + 1
        ):
            check_user_file_processing.run(mock_task, tenant_id=TEST_TENANT_ID)  # type: ignore[misc]

        mock_task.app.send_task.assert_not_called()


class TestPerFileGuardKey:
    """Protection 2: per-file Redis guard key prevents duplicate enqueue."""

    def test_guarded_file_not_re_enqueued(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """A file whose guard key is already set in Redis is skipped."""
        user = create_test_user(db_session, "guard_user")
        uf = _create_processing_user_file(db_session, user.id)

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        guard_key = _user_file_queued_key(uf.id)
        redis_client.setex(guard_key, CELERY_USER_FILE_PROCESSING_TASK_EXPIRES, 1)

        mock_task = _mock_self()

        try:
            with patch(_PATCH_QUEUE_LEN, return_value=0):
                check_user_file_processing.run(mock_task, tenant_id=TEST_TENANT_ID)  # type: ignore[misc]

            # send_task must not have been called with this specific file's ID
            for call in mock_task.app.send_task.call_args_list:
                kwargs = call.kwargs.get("kwargs", {})
                assert kwargs.get("user_file_id") != str(
                    uf.id
                ), f"File {uf.id} should have been skipped because its guard key exists"
        finally:
            redis_client.delete(guard_key)

    def test_guard_key_exists_in_redis_after_enqueue(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """After a file is enqueued its guard key is present in Redis with a TTL."""
        user = create_test_user(db_session, "guard_set_user")
        uf = _create_processing_user_file(db_session, user.id)

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        guard_key = _user_file_queued_key(uf.id)
        redis_client.delete(guard_key)  # clean slate

        mock_task = _mock_self()

        try:
            with patch(_PATCH_QUEUE_LEN, return_value=0):
                check_user_file_processing.run(mock_task, tenant_id=TEST_TENANT_ID)  # type: ignore[misc]

            assert redis_client.exists(
                guard_key
            ), "Guard key should be set in Redis after enqueue"
            ttl = int(redis_client.ttl(guard_key))  # type: ignore[arg-type]
            assert 0 < ttl <= CELERY_USER_FILE_PROCESSING_TASK_EXPIRES, (
                f"Guard key TTL {ttl}s is outside the expected range "
                f"(0, {CELERY_USER_FILE_PROCESSING_TASK_EXPIRES}]"
            )
        finally:
            redis_client.delete(guard_key)


class TestTaskExpiry:
    """Protection 3: every send_task call includes an expires value."""

    def test_send_task_called_with_expires(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """send_task is called with the correct queue, task name, and expires."""
        user = create_test_user(db_session, "expires_user")
        uf = _create_processing_user_file(db_session, user.id)

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        guard_key = _user_file_queued_key(uf.id)
        redis_client.delete(guard_key)

        mock_task = _mock_self()

        try:
            with patch(_PATCH_QUEUE_LEN, return_value=0):
                check_user_file_processing.run(mock_task, tenant_id=TEST_TENANT_ID)  # type: ignore[misc]

            # At least one task should have been submitted (for our file)
            assert (
                mock_task.app.send_task.call_count >= 1
            ), "Expected at least one task to be submitted"

            # Every submitted task must carry expires
            for call in mock_task.app.send_task.call_args_list:
                assert call.args[0] == OnyxCeleryTask.PROCESS_SINGLE_USER_FILE
                assert call.kwargs.get("queue") == OnyxCeleryQueues.USER_FILE_PROCESSING
                assert (
                    call.kwargs.get("expires")
                    == CELERY_USER_FILE_PROCESSING_TASK_EXPIRES
                ), (
                    "Task must be submitted with the correct expires value to prevent "
                    "stale task accumulation"
                )
        finally:
            redis_client.delete(guard_key)


class TestWorkerClearsGuardKey:
    """process_single_user_file removes the guard key when it picks up a task."""

    def test_guard_key_deleted_on_pickup(
        self,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """The guard key is deleted before the worker does any real work.

        We simulate an already-locked file so process_single_user_file returns
        early – but crucially, after the guard key deletion.
        """
        user_file_id = str(uuid4())

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)
        guard_key = _user_file_queued_key(user_file_id)

        # Simulate the guard key set when the beat enqueued the task
        redis_client.setex(guard_key, CELERY_USER_FILE_PROCESSING_TASK_EXPIRES, 1)
        assert redis_client.exists(guard_key), "Guard key must exist before pickup"

        # Hold the per-file processing lock so the worker exits early without
        # touching the database or file store.
        lock_key = _user_file_lock_key(user_file_id)
        processing_lock = redis_client.lock(lock_key, timeout=10)
        acquired = processing_lock.acquire(blocking=False)
        assert acquired, "Should be able to acquire the processing lock for this test"

        try:
            process_single_user_file.run(  # type: ignore[misc]
                _mock_self(),
                user_file_id=user_file_id,
                tenant_id=TEST_TENANT_ID,
            )
        finally:
            if processing_lock.owned():
                processing_lock.release()

        assert not redis_client.exists(
            guard_key
        ), "Guard key should be deleted when the worker picks up the task"
