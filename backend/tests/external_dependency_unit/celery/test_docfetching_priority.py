"""
External dependency unit tests for document processing job priority.

Tests that first-time indexing connectors (no last_successful_index_time)
get higher priority than re-indexing jobs from connectors that have
previously completed indexing.

Uses real Redis for locking and real database objects for CC pairs and search settings.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docfetching.task_creation_utils import (
    try_creating_docfetching_task,
)
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import OnyxCeleryPriority
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexModelStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import SearchSettings
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.constants import TEST_TENANT_ID


def _create_test_connector(db_session: Session, name: str) -> Connector:
    """Create a test connector with all required fields."""
    connector = Connector(
        name=name,
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=3600,
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(connector)
    return connector


def _create_test_credential(db_session: Session) -> Credential:
    """Create a test credential with all required fields."""
    credential = Credential(
        name=f"test_credential_{uuid4().hex[:8]}",
        source=DocumentSource.FILE,
        credential_json={},
        admin_public=True,
    )
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    return credential


def _create_test_cc_pair(
    db_session: Session,
    connector: Connector,
    credential: Credential,
    status: ConnectorCredentialPairStatus,
    name: str,
    last_successful_index_time: datetime | None = None,
) -> ConnectorCredentialPair:
    """Create a connector credential pair with the specified status."""
    cc_pair = ConnectorCredentialPair(
        name=name,
        connector_id=connector.id,
        credential_id=credential.id,
        status=status,
        access_type=AccessType.PUBLIC,
        last_successful_index_time=last_successful_index_time,
    )
    db_session.add(cc_pair)
    db_session.commit()
    db_session.refresh(cc_pair)
    return cc_pair


def _create_test_search_settings(
    db_session: Session, index_name: str
) -> SearchSettings:
    """Create test search settings with all required fields."""
    search_settings = SearchSettings(
        model_name="test-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        status=IndexModelStatus.PRESENT,
        index_name=index_name,
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
    db_session.add(search_settings)
    db_session.commit()
    db_session.refresh(search_settings)
    return search_settings


class TestDocfetchingTaskPriorityWithRealObjects:
    """
    Tests for document fetching task priority based on last_successful_index_time.

    Uses real Redis for locking and real database objects for CC pairs
    and search settings.
    """

    @pytest.mark.parametrize(
        "has_successful_index,expected_priority",
        [
            # First-time indexing (no last_successful_index_time) should get HIGH priority
            (False, OnyxCeleryPriority.HIGH),
            # Re-indexing (has last_successful_index_time) should get MEDIUM priority
            (True, OnyxCeleryPriority.MEDIUM),
        ],
    )
    @patch(
        "onyx.background.celery.tasks.docfetching.task_creation_utils.IndexingCoordination.try_create_index_attempt"
    )
    def test_priority_based_on_last_successful_index_time(
        self,
        mock_try_create_index_attempt: MagicMock,
        db_session: Session,
        has_successful_index: bool,
        expected_priority: OnyxCeleryPriority,
    ) -> None:
        """
        Test that first-time indexing connectors get higher priority than re-indexing.

        Priority is determined by last_successful_index_time:
        - None (never indexed): HIGH priority
        - Has timestamp (previously indexed): MEDIUM priority

        Uses real Redis for locking and real database objects.
        """
        # Create unique names to avoid conflicts between test runs
        unique_suffix = uuid4().hex[:8]

        # Determine last_successful_index_time based on the test case
        last_successful_index_time = (
            datetime.now(timezone.utc) if has_successful_index else None
        )

        # Create real database objects
        connector = _create_test_connector(
            db_session, f"test_connector_{has_successful_index}_{unique_suffix}"
        )
        credential = _create_test_credential(db_session)
        cc_pair = _create_test_cc_pair(
            db_session,
            connector,
            credential,
            ConnectorCredentialPairStatus.ACTIVE,
            name=f"test_cc_pair_{has_successful_index}_{unique_suffix}",
            last_successful_index_time=last_successful_index_time,
        )
        search_settings = _create_test_search_settings(
            db_session, f"test_index_{unique_suffix}"
        )

        # Mock the index attempt creation to return a valid ID
        mock_try_create_index_attempt.return_value = 12345

        # Mock celery app to capture task submission
        mock_celery_app = MagicMock()
        mock_celery_app.send_task.return_value = MagicMock()

        # Use real Redis client
        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)

        # Call the function with real objects
        result = try_creating_docfetching_task(
            celery_app=mock_celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            reindex=False,
            db_session=db_session,
            r=redis_client,
            tenant_id=TEST_TENANT_ID,
        )

        # Verify task was created
        assert result == 12345

        # Verify send_task was called with the expected priority
        mock_celery_app.send_task.assert_called_once()
        call_kwargs = mock_celery_app.send_task.call_args
        actual_priority = call_kwargs.kwargs["priority"]
        assert actual_priority == expected_priority, (
            f"Expected priority {expected_priority} for has_successful_index={has_successful_index}, "
            f"but got {actual_priority}"
        )

    @patch(
        "onyx.background.celery.tasks.docfetching.task_creation_utils.IndexingCoordination.try_create_index_attempt"
    )
    def test_no_task_created_when_deleting(
        self,
        mock_try_create_index_attempt: MagicMock,
        db_session: Session,
    ) -> None:
        """Test that no task is created when connector is in DELETING status."""
        unique_suffix = uuid4().hex[:8]

        connector = _create_test_connector(
            db_session, f"test_connector_deleting_{unique_suffix}"
        )
        credential = _create_test_credential(db_session)
        cc_pair = _create_test_cc_pair(
            db_session,
            connector,
            credential,
            ConnectorCredentialPairStatus.DELETING,
            name=f"test_cc_pair_deleting_{unique_suffix}",
        )
        search_settings = _create_test_search_settings(
            db_session, f"test_index_deleting_{unique_suffix}"
        )

        mock_celery_app = MagicMock()
        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)

        result = try_creating_docfetching_task(
            celery_app=mock_celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            reindex=False,
            db_session=db_session,
            r=redis_client,
            tenant_id=TEST_TENANT_ID,
        )

        # Verify no task was created
        assert result is None
        mock_celery_app.send_task.assert_not_called()
        mock_try_create_index_attempt.assert_not_called()

    @patch(
        "onyx.background.celery.tasks.docfetching.task_creation_utils.IndexingCoordination.try_create_index_attempt"
    )
    def test_redis_lock_prevents_concurrent_task_creation(
        self,
        mock_try_create_index_attempt: MagicMock,
        db_session: Session,
    ) -> None:
        """
        Test that the Redis lock prevents concurrent task creation attempts.

        This test uses real Redis to verify the locking mechanism works correctly.
        When the lock is already held, the function should return None without
        attempting to create a task.
        """
        unique_suffix = uuid4().hex[:8]

        connector = _create_test_connector(
            db_session, f"test_connector_lock_{unique_suffix}"
        )
        credential = _create_test_credential(db_session)
        cc_pair = _create_test_cc_pair(
            db_session,
            connector,
            credential,
            ConnectorCredentialPairStatus.INITIAL_INDEXING,
            name=f"test_cc_pair_lock_{unique_suffix}",
        )
        search_settings = _create_test_search_settings(
            db_session, f"test_index_lock_{unique_suffix}"
        )

        mock_try_create_index_attempt.return_value = 12345
        mock_celery_app = MagicMock()
        mock_celery_app.send_task.return_value = MagicMock()

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)

        # Acquire the lock before calling the function
        from onyx.configs.constants import DANSWER_REDIS_FUNCTION_LOCK_PREFIX

        lock = redis_client.lock(
            DANSWER_REDIS_FUNCTION_LOCK_PREFIX + "try_creating_indexing_task",
            timeout=30,
        )

        try:
            acquired = lock.acquire(blocking=False)
            assert acquired, "Failed to acquire lock for test"

            # Now try to create a task - should fail because lock is held
            result = try_creating_docfetching_task(
                celery_app=mock_celery_app,
                cc_pair=cc_pair,
                search_settings=search_settings,
                reindex=False,
                db_session=db_session,
                r=redis_client,
                tenant_id=TEST_TENANT_ID,
            )

            # Should return None because lock couldn't be acquired
            assert result is None
            mock_celery_app.send_task.assert_not_called()

        finally:
            # Always release the lock
            if lock.owned():
                lock.release()

    @patch(
        "onyx.background.celery.tasks.docfetching.task_creation_utils.IndexingCoordination.try_create_index_attempt"
    )
    def test_lock_released_after_successful_task_creation(
        self,
        mock_try_create_index_attempt: MagicMock,
        db_session: Session,
    ) -> None:
        """
        Test that the Redis lock is released after successful task creation.

        This verifies that subsequent calls can acquire the lock and create tasks.
        """
        unique_suffix = uuid4().hex[:8]

        connector = _create_test_connector(
            db_session, f"test_connector_release_{unique_suffix}"
        )
        credential = _create_test_credential(db_session)
        cc_pair = _create_test_cc_pair(
            db_session,
            connector,
            credential,
            ConnectorCredentialPairStatus.INITIAL_INDEXING,
            name=f"test_cc_pair_release_{unique_suffix}",
        )
        search_settings = _create_test_search_settings(
            db_session, f"test_index_release_{unique_suffix}"
        )

        mock_try_create_index_attempt.return_value = 12345
        mock_celery_app = MagicMock()
        mock_celery_app.send_task.return_value = MagicMock()

        redis_client = get_redis_client(tenant_id=TEST_TENANT_ID)

        # First call should succeed
        result1 = try_creating_docfetching_task(
            celery_app=mock_celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            reindex=False,
            db_session=db_session,
            r=redis_client,
            tenant_id=TEST_TENANT_ID,
        )
        assert result1 == 12345

        # Reset mocks for second call
        mock_celery_app.reset_mock()
        mock_try_create_index_attempt.reset_mock()
        mock_try_create_index_attempt.return_value = 67890

        # Second call should also succeed (lock was released)
        result2 = try_creating_docfetching_task(
            celery_app=mock_celery_app,
            cc_pair=cc_pair,
            search_settings=search_settings,
            reindex=False,
            db_session=db_session,
            r=redis_client,
            tenant_id=TEST_TENANT_ID,
        )
        assert result2 == 67890

        # Both calls should have submitted tasks
        mock_celery_app.send_task.assert_called_once()
