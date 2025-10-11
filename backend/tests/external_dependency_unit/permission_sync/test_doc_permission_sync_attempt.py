"""
Test suite for DocPermissionSyncAttempt CRUD operations.

Tests the basic CRUD operations for document permission sync attempts,
including creation, status updates, progress tracking, and querying.
"""

from datetime import datetime
from datetime import timezone

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import PermissionSyncStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.permission_sync_attempt import complete_doc_permission_sync_attempt
from onyx.db.permission_sync_attempt import create_doc_permission_sync_attempt
from onyx.db.permission_sync_attempt import get_doc_permission_sync_attempt
from onyx.db.permission_sync_attempt import (
    get_recent_doc_permission_sync_attempts_for_cc_pair,
)
from onyx.db.permission_sync_attempt import mark_doc_permission_sync_attempt_failed
from onyx.db.permission_sync_attempt import (
    mark_doc_permission_sync_attempt_in_progress,
)
from tests.external_dependency_unit.conftest import create_test_user


def _create_test_connector_credential_pair(
    db_session: Session, source: DocumentSource = DocumentSource.GOOGLE_DRIVE
) -> ConnectorCredentialPair:
    """Create a test connector credential pair for testing."""
    user = create_test_user(db_session, "test_user")

    connector = Connector(
        name=f"Test {source.value} Connector",
        source=source,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=datetime.now(timezone.utc),
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        credential_json={},
        user_id=user.id,
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Test CC Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.commit()

    return cc_pair


class TestDocPermissionSyncAttempt:

    def test_create_doc_permission_sync_attempt(self, db_session: Session) -> None:
        """Test creating a new doc permission sync attempt."""
        cc_pair = _create_test_connector_credential_pair(db_session)

        attempt_id = create_doc_permission_sync_attempt(
            connector_credential_pair_id=cc_pair.id,
            db_session=db_session,
        )

        assert attempt_id is not None
        assert isinstance(attempt_id, int)

        # Verify the attempt was created with correct defaults
        attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.connector_credential_pair_id == cc_pair.id
        assert attempt.status == PermissionSyncStatus.NOT_STARTED
        assert attempt.total_docs_synced == 0
        assert attempt.docs_with_permission_errors == 0
        assert attempt.time_started is None
        assert attempt.time_finished is None
        assert attempt.time_created is not None

    def test_get_doc_permission_sync_attempt(self, db_session: Session) -> None:
        """Test retrieving a doc permission sync attempt by ID."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)

        # Test basic retrieval
        attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.id == attempt_id

        # Test with eager loading
        attempt_with_connector = get_doc_permission_sync_attempt(
            db_session, attempt_id, eager_load_connector=True
        )
        assert attempt_with_connector is not None
        assert attempt_with_connector.connector_credential_pair is not None
        assert attempt_with_connector.connector_credential_pair.id == cc_pair.id

        # Test non-existent ID
        non_existent_attempt = get_doc_permission_sync_attempt(db_session, 99999)
        assert non_existent_attempt is None

    def test_mark_doc_permission_sync_attempt_in_progress(
        self, db_session: Session
    ) -> None:
        """Test marking a doc permission sync attempt as in progress."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)

        # Mark as in progress
        updated_attempt = mark_doc_permission_sync_attempt_in_progress(
            attempt_id, db_session
        )

        assert updated_attempt.status == PermissionSyncStatus.IN_PROGRESS
        assert updated_attempt.time_started is not None
        assert updated_attempt.time_finished is None

        # Verify it fails if already in progress
        with pytest.raises(RuntimeError, match="not in NOT_STARTED status"):
            mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)

    def test_mark_doc_permission_sync_attempt_failed(self, db_session: Session) -> None:
        """Test marking a doc permission sync attempt as failed."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)

        # Mark as failed with error message (should work even without starting)
        error_msg = "Sync process crashed unexpectedly"
        mark_doc_permission_sync_attempt_failed(
            attempt_id, db_session, error_message=error_msg
        )

        # Verify the status and timestamps
        attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status == PermissionSyncStatus.FAILED
        assert attempt.time_started is not None
        assert attempt.time_finished is not None
        assert attempt.error_message == error_msg

    def test_get_recent_doc_permission_sync_attempts_for_cc_pair(
        self, db_session: Session
    ) -> None:
        """Test retrieving recent doc permission sync attempts for a connector credential pair."""
        cc_pair = _create_test_connector_credential_pair(db_session)

        # Create multiple attempts
        attempt_ids = []
        for i in range(5):
            attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)
            attempt_ids.append(attempt_id)

        # Get recent attempts
        recent_attempts = get_recent_doc_permission_sync_attempts_for_cc_pair(
            cc_pair_id=cc_pair.id,
            limit=3,
            db_session=db_session,
        )

        assert len(recent_attempts) == 3

        # Verify they are ordered by time_created descending (most recent first)
        for i in range(len(recent_attempts) - 1):
            assert (
                recent_attempts[i].time_created >= recent_attempts[i + 1].time_created
            )

        # Verify they all belong to the correct cc_pair
        for attempt in recent_attempts:
            assert attempt.connector_credential_pair_id == cc_pair.id

        # Test with different cc_pair (should return empty)
        other_cc_pair = _create_test_connector_credential_pair(
            db_session, source=DocumentSource.SLACK
        )
        other_attempts = get_recent_doc_permission_sync_attempts_for_cc_pair(
            cc_pair_id=other_cc_pair.id,
            limit=10,
            db_session=db_session,
        )
        assert len(other_attempts) == 0

    def test_status_enum_methods(self, db_session: Session) -> None:
        """Test the status enum helper methods."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)

        # Test NOT_STARTED status
        attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert not attempt.status.is_terminal()
        assert not attempt.status.is_successful()

        # Test IN_PROGRESS status
        mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)
        attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert not attempt.status.is_terminal()
        assert not attempt.status.is_successful()

        # Test SUCCESS status via complete function
        complete_doc_permission_sync_attempt(
            db_session=db_session,
            attempt_id=attempt_id,
            total_docs_synced=100,
            docs_with_permission_errors=0,
        )
        attempt = get_doc_permission_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status.is_terminal()
        assert attempt.status.is_successful()

        # Test FAILED status (create new attempt)
        failed_attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)
        mark_doc_permission_sync_attempt_failed(
            failed_attempt_id, db_session, error_message="Test failure"
        )
        failed_attempt = get_doc_permission_sync_attempt(db_session, failed_attempt_id)
        assert failed_attempt is not None
        assert failed_attempt.status.is_terminal()
        assert not failed_attempt.status.is_successful()

        # Test COMPLETED_WITH_ERRORS status via complete function (create new attempt)
        error_attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)
        mark_doc_permission_sync_attempt_in_progress(error_attempt_id, db_session)
        complete_doc_permission_sync_attempt(
            db_session=db_session,
            attempt_id=error_attempt_id,
            total_docs_synced=100,
            docs_with_permission_errors=10,
        )
        error_attempt = get_doc_permission_sync_attempt(db_session, error_attempt_id)
        assert error_attempt is not None
        assert error_attempt.status.is_terminal()
        assert (
            error_attempt.status.is_successful()
        )  # Completed with errors is still "successful"

    def test_complete_doc_permission_sync_attempt_success(
        self, db_session: Session
    ) -> None:
        """Test completing a doc permission sync attempt without errors."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)

        # Mark as in progress first
        mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)

        # Complete without errors
        completed_attempt = complete_doc_permission_sync_attempt(
            db_session=db_session,
            attempt_id=attempt_id,
            total_docs_synced=100,
            docs_with_permission_errors=0,
        )

        assert completed_attempt.status == PermissionSyncStatus.SUCCESS
        assert completed_attempt.total_docs_synced == 100
        assert completed_attempt.docs_with_permission_errors == 0
        assert completed_attempt.time_finished is not None

    def test_complete_doc_permission_sync_attempt_with_errors(
        self, db_session: Session
    ) -> None:
        """Test completing a doc permission sync attempt with errors."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)

        # Mark as in progress first
        mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)

        # Complete with errors
        completed_attempt = complete_doc_permission_sync_attempt(
            db_session=db_session,
            attempt_id=attempt_id,
            total_docs_synced=100,
            docs_with_permission_errors=15,
        )

        assert completed_attempt.status == PermissionSyncStatus.COMPLETED_WITH_ERRORS
        assert completed_attempt.total_docs_synced == 100
        assert completed_attempt.docs_with_permission_errors == 15
        assert completed_attempt.time_finished is not None

    def test_complete_doc_permission_sync_attempt_can_be_called_multiple_times(
        self, db_session: Session
    ) -> None:
        """Test that complete can be called multiple times if needed (accumulates correctly)."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_doc_permission_sync_attempt(cc_pair.id, db_session)

        # Mark as in progress
        mark_doc_permission_sync_attempt_in_progress(attempt_id, db_session)

        # Complete once
        first_complete = complete_doc_permission_sync_attempt(
            db_session=db_session,
            attempt_id=attempt_id,
            total_docs_synced=50,
            docs_with_permission_errors=5,
        )

        # Verify first completion
        assert first_complete.status == PermissionSyncStatus.COMPLETED_WITH_ERRORS
        assert first_complete.total_docs_synced == 50
        assert first_complete.docs_with_permission_errors == 5
        assert first_complete.time_finished is not None

        # Call complete again (simulating additional batch processing)
        second_complete = complete_doc_permission_sync_attempt(
            db_session=db_session,
            attempt_id=attempt_id,
            total_docs_synced=50,
            docs_with_permission_errors=10,
        )

        # Should accumulate progress from both calls
        assert second_complete.status == PermissionSyncStatus.COMPLETED_WITH_ERRORS
        assert second_complete.total_docs_synced == 100
        assert second_complete.docs_with_permission_errors == 15
        assert second_complete.time_finished is not None
