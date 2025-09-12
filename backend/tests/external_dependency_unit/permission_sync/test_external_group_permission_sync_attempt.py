"""
Test suite for ExternalGroupPermissionSyncAttempt CRUD operations.

Tests the basic CRUD operations for external group permission sync attempts,
including creation, status updates, progress tracking, and querying.
Supports both connector-specific and global group sync attempts.
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
from onyx.db.models import ExternalGroupPermissionSyncAttempt
from onyx.db.permission_sync_attempt import (
    create_external_group_sync_attempt,
)
from onyx.db.permission_sync_attempt import (
    get_external_group_sync_attempt,
)
from onyx.db.permission_sync_attempt import (
    get_recent_external_group_sync_attempts_for_cc_pair,
)
from onyx.db.permission_sync_attempt import (
    mark_external_group_sync_attempt_completed_with_errors,
)
from onyx.db.permission_sync_attempt import (
    mark_external_group_sync_attempt_failed,
)
from onyx.db.permission_sync_attempt import (
    mark_external_group_sync_attempt_in_progress,
)
from onyx.db.permission_sync_attempt import (
    mark_external_group_sync_attempt_succeeded,
)
from onyx.db.permission_sync_attempt import (
    update_external_group_sync_progress,
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


def _cleanup_global_external_group_sync_attempts(db_session: Session) -> None:
    """Clean up any existing global external group sync attempts from previous test runs."""
    # Delete all global attempts (where connector_credential_pair_id is None)
    db_session.query(ExternalGroupPermissionSyncAttempt).filter(
        ExternalGroupPermissionSyncAttempt.connector_credential_pair_id.is_(None)
    ).delete()
    db_session.commit()


class TestExternalGroupPermissionSyncAttempt:

    def test_create_external_group_sync_attempt_with_cc_pair(
        self, db_session: Session
    ) -> None:
        """Test creating a new external group sync attempt for a specific connector."""
        cc_pair = _create_test_connector_credential_pair(db_session)

        attempt_id = create_external_group_sync_attempt(
            connector_credential_pair_id=cc_pair.id,
            db_session=db_session,
        )

        assert attempt_id is not None
        assert isinstance(attempt_id, int)

        # Verify the attempt was created with correct defaults
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.connector_credential_pair_id == cc_pair.id
        assert attempt.status == PermissionSyncStatus.NOT_STARTED
        assert attempt.total_users_processed == 0
        assert attempt.total_groups_processed == 0
        assert attempt.total_group_memberships_synced == 0
        assert attempt.time_started is None
        assert attempt.time_finished is None
        assert attempt.time_created is not None

    def test_create_global_external_group_sync_attempt(
        self, db_session: Session
    ) -> None:
        """Test creating a new global external group sync attempt."""
        attempt_id = create_external_group_sync_attempt(
            connector_credential_pair_id=None,  # Global sync
            db_session=db_session,
        )

        assert attempt_id is not None
        assert isinstance(attempt_id, int)

        # Verify the attempt was created as global
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.connector_credential_pair_id is None
        assert attempt.status == PermissionSyncStatus.NOT_STARTED

    def test_get_external_group_sync_attempt(self, db_session: Session) -> None:
        """Test retrieving an external group sync attempt by ID."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Test basic retrieval
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.id == attempt_id

        # Test with eager loading
        attempt_with_cc_pair = get_external_group_sync_attempt(
            db_session, attempt_id, eager_load_cc_pair=True
        )
        assert attempt_with_cc_pair is not None
        assert attempt_with_cc_pair.connector_credential_pair is not None
        assert attempt_with_cc_pair.connector_credential_pair.id == cc_pair.id

        # Test non-existent ID
        non_existent_attempt = get_external_group_sync_attempt(db_session, 99999)
        assert non_existent_attempt is None

    def test_mark_external_group_sync_attempt_in_progress(
        self, db_session: Session
    ) -> None:
        """Test marking an external group sync attempt as in progress."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Mark as in progress
        updated_attempt = mark_external_group_sync_attempt_in_progress(
            attempt_id, db_session
        )

        assert updated_attempt.status == PermissionSyncStatus.IN_PROGRESS
        assert updated_attempt.time_started is not None
        assert updated_attempt.time_finished is None

        # Verify it fails if already in progress
        with pytest.raises(RuntimeError, match="not in NOT_STARTED status"):
            mark_external_group_sync_attempt_in_progress(attempt_id, db_session)

    def test_mark_external_group_sync_attempt_succeeded(
        self, db_session: Session
    ) -> None:
        """Test marking an external group sync attempt as successful."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Start the attempt first
        mark_external_group_sync_attempt_in_progress(attempt_id, db_session)

        # Mark as succeeded
        updated_attempt = mark_external_group_sync_attempt_succeeded(
            attempt_id, db_session
        )

        assert updated_attempt.status == PermissionSyncStatus.SUCCESS
        assert updated_attempt.time_finished is not None

    def test_mark_external_group_sync_attempt_completed_with_errors(
        self, db_session: Session
    ) -> None:
        """Test marking an external group sync attempt as completed with errors."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Start the attempt first
        mark_external_group_sync_attempt_in_progress(attempt_id, db_session)

        # Mark as completed with errors (this is still considered successful)
        # No error message should be set since the sync itself succeeded
        updated_attempt = mark_external_group_sync_attempt_completed_with_errors(
            attempt_id, db_session
        )

        assert updated_attempt.status == PermissionSyncStatus.COMPLETED_WITH_ERRORS
        assert updated_attempt.time_finished is not None
        assert (
            updated_attempt.error_message is None
        )  # No error message for successful completion

    def test_mark_external_group_sync_attempt_failed(self, db_session: Session) -> None:
        """Test marking an external group sync attempt as failed."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Mark as failed with error message (should work even without starting)
        error_msg_1 = "External group sync service unavailable"
        mark_external_group_sync_attempt_failed(
            attempt_id, db_session, error_message=error_msg_1
        )

        # Verify the status and timestamps
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status == PermissionSyncStatus.FAILED
        assert attempt.time_started is not None  # Should be set if not already set
        assert attempt.time_finished is not None
        assert attempt.error_message == error_msg_1

        # Test with error message
        attempt_id_2 = create_external_group_sync_attempt(cc_pair.id, db_session)
        error_msg = "Connection timeout to external service"
        mark_external_group_sync_attempt_failed(
            attempt_id_2, db_session, error_message=error_msg
        )

        # Verify the error message was stored
        attempt_2 = get_external_group_sync_attempt(db_session, attempt_id_2)
        assert attempt_2 is not None
        assert attempt_2.status == PermissionSyncStatus.FAILED
        assert attempt_2.error_message == error_msg

    def test_update_external_group_sync_progress(self, db_session: Session) -> None:
        """Test updating progress counters of an external group sync attempt."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Update progress
        update_external_group_sync_progress(
            db_session=db_session,
            attempt_id=attempt_id,
            total_users_processed=100,
            total_groups_processed=10,
            total_group_memberships_synced=250,
        )

        # Verify the update
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.total_users_processed == 100
        assert attempt.total_groups_processed == 10
        assert attempt.total_group_memberships_synced == 250

        # Update again (should add to existing values)
        update_external_group_sync_progress(
            db_session=db_session,
            attempt_id=attempt_id,
            total_users_processed=50,
            total_groups_processed=5,
            total_group_memberships_synced=125,
        )

        # Verify the cumulative update
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.total_users_processed == 150
        assert attempt.total_groups_processed == 15
        assert attempt.total_group_memberships_synced == 375

    def test_get_recent_external_group_sync_attempts_for_cc_pair(
        self, db_session: Session
    ) -> None:
        """Test retrieving recent external group sync attempts for a connector credential pair."""
        cc_pair = _create_test_connector_credential_pair(db_session)

        # Create multiple attempts for the cc_pair
        attempt_ids = []
        for i in range(5):
            attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
            attempt_ids.append(attempt_id)

        # Get recent attempts
        recent_attempts = get_recent_external_group_sync_attempts_for_cc_pair(
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
        other_attempts = get_recent_external_group_sync_attempts_for_cc_pair(
            cc_pair_id=other_cc_pair.id,
            limit=10,
            db_session=db_session,
        )
        assert len(other_attempts) == 0

    def test_get_recent_global_external_group_sync_attempts(
        self, db_session: Session
    ) -> None:
        """Test retrieving recent global external group sync attempts."""
        # Clean up any existing global attempts from previous test runs
        _cleanup_global_external_group_sync_attempts(db_session)

        # Create a cc_pair specific attempt
        cc_pair = _create_test_connector_credential_pair(db_session)
        create_external_group_sync_attempt(cc_pair.id, db_session)

        # Create multiple global attempts
        global_attempt_ids = []
        for i in range(3):
            attempt_id = create_external_group_sync_attempt(None, db_session)  # Global
            global_attempt_ids.append(attempt_id)

        # Get recent global attempts
        recent_global_attempts = get_recent_external_group_sync_attempts_for_cc_pair(
            cc_pair_id=None,  # Global
            limit=5,
            db_session=db_session,
        )

        assert len(recent_global_attempts) == 3

        # Verify they are all global (cc_pair_id is None)
        for attempt in recent_global_attempts:
            assert attempt.connector_credential_pair_id is None

        # Verify they are ordered by time_created descending
        for i in range(len(recent_global_attempts) - 1):
            assert (
                recent_global_attempts[i].time_created
                >= recent_global_attempts[i + 1].time_created
            )

    def test_status_enum_methods(self, db_session: Session) -> None:
        """Test the status enum helper methods."""
        cc_pair = _create_test_connector_credential_pair(db_session)
        attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Test NOT_STARTED status
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert not attempt.status.is_terminal()
        assert not attempt.status.is_successful()

        # Test IN_PROGRESS status
        mark_external_group_sync_attempt_in_progress(attempt_id, db_session)
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert not attempt.status.is_terminal()
        assert not attempt.status.is_successful()

        # Test SUCCESS status
        mark_external_group_sync_attempt_succeeded(attempt_id, db_session)
        attempt = get_external_group_sync_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status.is_terminal()
        assert attempt.status.is_successful()

        # Test FAILED status (create new attempt)
        failed_attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
        mark_external_group_sync_attempt_failed(
            failed_attempt_id, db_session, error_message="Test failure"
        )
        failed_attempt = get_external_group_sync_attempt(db_session, failed_attempt_id)
        assert failed_attempt is not None
        assert failed_attempt.status.is_terminal()
        assert not failed_attempt.status.is_successful()

        # Test COMPLETED_WITH_ERRORS status (create new attempt)
        error_attempt_id = create_external_group_sync_attempt(cc_pair.id, db_session)
        mark_external_group_sync_attempt_in_progress(error_attempt_id, db_session)
        mark_external_group_sync_attempt_completed_with_errors(
            error_attempt_id, db_session
        )
        error_attempt = get_external_group_sync_attempt(db_session, error_attempt_id)
        assert error_attempt is not None
        assert error_attempt.status.is_terminal()
        assert (
            error_attempt.status.is_successful()
        )  # Completed with errors is still "successful"

    def test_global_vs_connector_specific_attempts(self, db_session: Session) -> None:
        """Test that global and connector-specific attempts are properly separated."""
        # Clean up any existing global attempts from previous test runs
        _cleanup_global_external_group_sync_attempts(db_session)

        cc_pair = _create_test_connector_credential_pair(db_session)

        # Create connector-specific attempts
        cc_attempt_1 = create_external_group_sync_attempt(cc_pair.id, db_session)
        cc_attempt_2 = create_external_group_sync_attempt(cc_pair.id, db_session)

        # Create global attempts
        global_attempt_1 = create_external_group_sync_attempt(None, db_session)
        global_attempt_2 = create_external_group_sync_attempt(None, db_session)

        # Verify connector-specific attempts
        cc_attempts = get_recent_external_group_sync_attempts_for_cc_pair(
            cc_pair_id=cc_pair.id, limit=10, db_session=db_session
        )
        assert len(cc_attempts) == 2
        cc_attempt_ids = {attempt.id for attempt in cc_attempts}
        assert cc_attempt_ids == {cc_attempt_1, cc_attempt_2}

        # Verify global attempts
        global_attempts = get_recent_external_group_sync_attempts_for_cc_pair(
            cc_pair_id=None, limit=10, db_session=db_session
        )
        assert len(global_attempts) == 2
        global_attempt_ids = {attempt.id for attempt in global_attempts}
        assert global_attempt_ids == {global_attempt_1, global_attempt_2}
