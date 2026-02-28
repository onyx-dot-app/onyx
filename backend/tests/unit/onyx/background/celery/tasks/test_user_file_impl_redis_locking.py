"""Tests for the _impl functions' redis_locking parameter.

Verifies that:
- redis_locking=True acquires/releases Redis locks and clears queued keys
- redis_locking=False skips all Redis operations entirely
- Both paths execute the same business logic (DB lookup, status check)
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from onyx.background.celery.tasks.user_file_processing.tasks import (
    _delete_user_file_impl,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _process_user_file_impl,
)
from onyx.background.celery.tasks.user_file_processing.tasks import (
    _project_sync_user_file_impl,
)

TASKS_MODULE = "onyx.background.celery.tasks.user_file_processing.tasks"


def _mock_session_returning_none() -> MagicMock:
    """Return a mock session whose .get() returns None (file not found)."""
    session = MagicMock()
    session.get.return_value = None
    session.execute.return_value.scalar_one_or_none.return_value = None
    return session


# ------------------------------------------------------------------
# _process_user_file_impl
# ------------------------------------------------------------------


class TestProcessUserFileImpl:
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_true_acquires_and_releases_lock(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        redis_client = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock.owned.return_value = True
        redis_client.lock.return_value = lock
        mock_get_redis.return_value = redis_client

        session = _mock_session_returning_none()
        mock_get_session.return_value.__enter__.return_value = session

        user_file_id = str(uuid4())
        _process_user_file_impl(
            user_file_id=user_file_id,
            tenant_id="test-tenant",
            redis_locking=True,
        )

        mock_get_redis.assert_called_once_with(tenant_id="test-tenant")
        redis_client.delete.assert_called_once()
        lock.acquire.assert_called_once_with(blocking=False)
        lock.release.assert_called_once()

    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_true_skips_when_lock_held(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        redis_client = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = False
        redis_client.lock.return_value = lock
        mock_get_redis.return_value = redis_client

        _process_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=True,
        )

        lock.acquire.assert_called_once()
        mock_get_session.assert_not_called()

    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_false_skips_redis_entirely(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        session = _mock_session_returning_none()
        mock_get_session.return_value.__enter__.return_value = session

        _process_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=False,
        )

        mock_get_redis.assert_not_called()
        mock_get_session.assert_called_once()

    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_both_paths_call_db_get(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        """Both redis_locking=True and False should call db_session.get(UserFile, ...)."""
        redis_client = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock.owned.return_value = True
        redis_client.lock.return_value = lock
        mock_get_redis.return_value = redis_client

        session = _mock_session_returning_none()
        mock_get_session.return_value.__enter__.return_value = session

        uid = str(uuid4())

        _process_user_file_impl(user_file_id=uid, tenant_id="t", redis_locking=True)
        call_count_true = session.get.call_count

        session.reset_mock()
        mock_get_session.reset_mock()
        mock_get_session.return_value.__enter__.return_value = session

        _process_user_file_impl(user_file_id=uid, tenant_id="t", redis_locking=False)
        call_count_false = session.get.call_count

        assert call_count_true == call_count_false == 1


# ------------------------------------------------------------------
# _delete_user_file_impl
# ------------------------------------------------------------------


class TestDeleteUserFileImpl:
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_true_acquires_and_releases_lock(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        redis_client = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock.owned.return_value = True
        redis_client.lock.return_value = lock
        mock_get_redis.return_value = redis_client

        session = _mock_session_returning_none()
        mock_get_session.return_value.__enter__.return_value = session

        _delete_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=True,
        )

        mock_get_redis.assert_called_once()
        lock.acquire.assert_called_once_with(blocking=False)
        lock.release.assert_called_once()

    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_true_skips_when_lock_held(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        redis_client = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = False
        redis_client.lock.return_value = lock
        mock_get_redis.return_value = redis_client

        _delete_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=True,
        )

        lock.acquire.assert_called_once()
        mock_get_session.assert_not_called()

    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_false_skips_redis_entirely(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        session = _mock_session_returning_none()
        mock_get_session.return_value.__enter__.return_value = session

        _delete_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=False,
        )

        mock_get_redis.assert_not_called()
        mock_get_session.assert_called_once()


# ------------------------------------------------------------------
# _project_sync_user_file_impl
# ------------------------------------------------------------------


class TestProjectSyncUserFileImpl:
    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_true_acquires_and_releases_lock(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        redis_client = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = True
        lock.owned.return_value = True
        redis_client.lock.return_value = lock
        mock_get_redis.return_value = redis_client

        session = _mock_session_returning_none()
        mock_get_session.return_value.__enter__.return_value = session

        _project_sync_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=True,
        )

        mock_get_redis.assert_called_once()
        redis_client.delete.assert_called_once()
        lock.acquire.assert_called_once_with(blocking=False)
        lock.release.assert_called_once()

    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_true_skips_when_lock_held(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        redis_client = MagicMock()
        lock = MagicMock()
        lock.acquire.return_value = False
        redis_client.lock.return_value = lock
        mock_get_redis.return_value = redis_client

        _project_sync_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=True,
        )

        lock.acquire.assert_called_once()
        mock_get_session.assert_not_called()

    @patch(f"{TASKS_MODULE}.get_session_with_current_tenant")
    @patch(f"{TASKS_MODULE}.get_redis_client")
    def test_redis_locking_false_skips_redis_entirely(
        self,
        mock_get_redis: MagicMock,
        mock_get_session: MagicMock,
    ) -> None:
        session = _mock_session_returning_none()
        mock_get_session.return_value.__enter__.return_value = session

        _project_sync_user_file_impl(
            user_file_id=str(uuid4()),
            tenant_id="test-tenant",
            redis_locking=False,
        )

        mock_get_redis.assert_not_called()
        mock_get_session.assert_called_once()
