from collections.abc import Generator
from unittest.mock import Mock
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.external_group_syncing.tasks import (
    _perform_external_group_sync,
)
from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import PublicExternalUserGroup
from onyx.db.models import User__ExternalUserGroupId
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.constants import TEST_TENANT_ID


def _create_test_connector_credential_pair(
    db_session: Session, source: DocumentSource = DocumentSource.GOOGLE_DRIVE
) -> ConnectorCredentialPair:
    """Helper to create a test connector credential pair"""
    # For Google Drive, we need to include required config parameters
    connector_config = {}
    if source == DocumentSource.GOOGLE_DRIVE:
        connector_config = {
            "include_shared_drives": True,  # At least one of these is required
        }

    connector = Connector(
        name="Test Connector",
        source=source,
        input_type=InputType.POLL,
        connector_specific_config=connector_config,
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()  # To get the connector ID

    credential = Credential(
        source=source,
        credential_json={},
        user_id=None,
    )
    db_session.add(credential)
    db_session.flush()  # To get the credential ID

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Test CC Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.SYNC,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.commit()
    db_session.refresh(cc_pair)
    return cc_pair


def _get_user_external_groups(
    db_session: Session, cc_pair_id: int, include_stale: bool = False
) -> list[User__ExternalUserGroupId]:
    """Helper to get user external groups from database"""
    query = select(User__ExternalUserGroupId).where(
        User__ExternalUserGroupId.cc_pair_id == cc_pair_id
    )
    if not include_stale:
        query = query.where(User__ExternalUserGroupId.stale.is_(False))

    return list(db_session.scalars(query).all())


def _get_public_external_groups(
    db_session: Session, cc_pair_id: int, include_stale: bool = False
) -> list[PublicExternalUserGroup]:
    """Helper to get public external groups from database"""
    query = select(PublicExternalUserGroup).where(
        PublicExternalUserGroup.cc_pair_id == cc_pair_id
    )
    if not include_stale:
        query = query.where(PublicExternalUserGroup.stale.is_(False))

    return list(db_session.scalars(query).all())


class TestPerformExternalGroupSync:

    def test_initial_group_sync(self, db_session: Session) -> None:
        """Test syncing external groups for the first time (initial sync)"""
        # Create test data
        user1 = create_test_user(db_session, "user1")
        user2 = create_test_user(db_session, "user2")
        user3 = create_test_user(db_session, "user3")
        cc_pair = _create_test_connector_credential_pair(db_session)

        # Mock external groups data as a generator that yields the expected groups
        mock_groups = [
            ExternalUserGroup(id="group1", user_emails=[user1.email, user2.email]),
            ExternalUserGroup(id="group2", user_emails=[user2.email, user3.email]),
            ExternalUserGroup(
                id="public_group", user_emails=[user1.email], gives_anyone_access=True
            ),
        ]

        def mock_group_sync_func(
            tenant_id: str, cc_pair: ConnectorCredentialPair
        ) -> Generator[ExternalUserGroup, None, None]:
            for group in mock_groups:
                yield group

        # Verify no groups exist initially
        assert len(_get_user_external_groups(db_session, cc_pair.id)) == 0
        assert len(_get_public_external_groups(db_session, cc_pair.id)) == 0

        with patch(
            "ee.onyx.background.celery.tasks.external_group_syncing.tasks.get_source_perm_sync_config"
        ) as mock_config:
            # Mock sync config
            mock_group_config = Mock()
            mock_group_config.group_sync_func = mock_group_sync_func

            mock_sync_config = Mock()
            mock_sync_config.group_sync_config = mock_group_config

            mock_config.return_value = mock_sync_config

            # Run the sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify user groups were created
            user_groups = _get_user_external_groups(db_session, cc_pair.id)
            assert (
                len(user_groups) == 5
            )  # user1+2 in group1, user2+3 in group2, user1 in public_group

            # Verify group names are properly prefixed
            expected_group1_id = build_ext_group_name_for_onyx(
                "group1", DocumentSource.GOOGLE_DRIVE
            )
            expected_group2_id = build_ext_group_name_for_onyx(
                "group2", DocumentSource.GOOGLE_DRIVE
            )
            expected_public_group_id = build_ext_group_name_for_onyx(
                "public_group", DocumentSource.GOOGLE_DRIVE
            )

            group_ids = {ug.external_user_group_id for ug in user_groups}
            assert expected_group1_id in group_ids
            assert expected_group2_id in group_ids
            assert expected_public_group_id in group_ids

            # Verify public group was created
            public_groups = _get_public_external_groups(db_session, cc_pair.id)
            assert len(public_groups) == 1
            assert public_groups[0].external_user_group_id == expected_public_group_id
            assert public_groups[0].stale is False

            # Verify all groups are not stale
            for ug in user_groups:
                assert ug.stale is False

    def test_update_existing_groups(self, db_session: Session) -> None:
        """Test updating existing groups (adding/removing users)"""
        # Create test data
        user1 = create_test_user(db_session, "user1")
        user2 = create_test_user(db_session, "user2")
        user3 = create_test_user(db_session, "user3")
        cc_pair = _create_test_connector_credential_pair(db_session)

        # Initial sync with original groups
        def initial_group_sync_func(
            tenant_id: str, cc_pair: ConnectorCredentialPair
        ) -> Generator[ExternalUserGroup, None, None]:
            yield ExternalUserGroup(id="group1", user_emails=[user1.email, user2.email])
            yield ExternalUserGroup(id="group2", user_emails=[user2.email])

        # For now, verify test setup is working
        assert len(_get_user_external_groups(db_session, cc_pair.id)) == 0

        with patch(
            "ee.onyx.background.celery.tasks.external_group_syncing.tasks.get_source_perm_sync_config"
        ) as mock_config:
            # Mock sync config
            mock_group_config = Mock()
            mock_group_config.group_sync_func = initial_group_sync_func

            mock_sync_config = Mock()
            mock_sync_config.group_sync_config = mock_group_config

            mock_config.return_value = mock_sync_config

            # Run initial sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify initial state
            initial_user_groups = _get_user_external_groups(db_session, cc_pair.id)
            assert (
                len(initial_user_groups) == 3
            )  # user1+user2 in group1, user2 in group2

            # Updated sync with modified groups
            def updated_group_sync_func(
                tenant_id: str, cc_pair: ConnectorCredentialPair
            ) -> Generator[ExternalUserGroup, None, None]:
                # group1 now has user1 and user3 (user2 removed, user3 added)
                yield ExternalUserGroup(
                    id="group1", user_emails=[user1.email, user3.email]
                )
                # group2 now has all three users (user1 and user3 added)
                yield ExternalUserGroup(
                    id="group2", user_emails=[user1.email, user2.email, user3.email]
                )

            # Update the mock function
            mock_group_config.group_sync_func = updated_group_sync_func

            # Run updated sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify updated state
            updated_user_groups = _get_user_external_groups(db_session, cc_pair.id)
            assert (
                len(updated_user_groups) == 5
            )  # user1+user3 in group1, user1+user2+user3 in group2

            # Verify specific user-group mappings
            expected_group1_id = build_ext_group_name_for_onyx(
                "group1", DocumentSource.GOOGLE_DRIVE
            )
            expected_group2_id = build_ext_group_name_for_onyx(
                "group2", DocumentSource.GOOGLE_DRIVE
            )

            group1_users = {
                ug.user_id
                for ug in updated_user_groups
                if ug.external_user_group_id == expected_group1_id
            }
            group2_users = {
                ug.user_id
                for ug in updated_user_groups
                if ug.external_user_group_id == expected_group2_id
            }

            assert user1.id in group1_users and user3.id in group1_users
            assert user2.id not in group1_users  # user2 was removed from group1
            assert (
                user1.id in group2_users
                and user2.id in group2_users
                and user3.id in group2_users
            )

            # Verify no stale groups remain
            for ug in updated_user_groups:
                assert ug.stale is False

    def test_remove_groups(self, db_session: Session) -> None:
        """Test removing groups (groups that no longer exist in external system)"""
        # Create test data
        user1 = create_test_user(db_session, "user1")
        user2 = create_test_user(db_session, "user2")
        cc_pair = _create_test_connector_credential_pair(db_session)

        # Initial sync with multiple groups
        def initial_group_sync_func(
            tenant_id: str, cc_pair: ConnectorCredentialPair
        ) -> Generator[ExternalUserGroup, None, None]:
            yield ExternalUserGroup(id="group1", user_emails=[user1.email, user2.email])
            yield ExternalUserGroup(id="group2", user_emails=[user1.email])
            yield ExternalUserGroup(
                id="public_group", user_emails=[user1.email], gives_anyone_access=True
            )

        assert len(_get_user_external_groups(db_session, cc_pair.id)) == 0
        assert len(_get_public_external_groups(db_session, cc_pair.id)) == 0

        with patch(
            "ee.onyx.background.celery.tasks.external_group_syncing.tasks.get_source_perm_sync_config"
        ) as mock_config:
            # Mock sync config
            mock_group_config = Mock()
            mock_group_config.group_sync_func = initial_group_sync_func

            mock_sync_config = Mock()
            mock_sync_config.group_sync_config = mock_group_config

            mock_config.return_value = mock_sync_config

            # Run initial sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify initial state
            initial_user_groups = _get_user_external_groups(db_session, cc_pair.id)
            initial_public_groups = _get_public_external_groups(db_session, cc_pair.id)
            assert (
                len(initial_user_groups) == 4
            )  # 2 in group1, 1 in group2, 1 in public_group
            assert len(initial_public_groups) == 1

            # Updated sync with only one group remaining
            def updated_group_sync_func(
                tenant_id: str, cc_pair: ConnectorCredentialPair
            ) -> Generator[ExternalUserGroup, None, None]:
                # Only group1 remains, group2 and public_group are removed
                yield ExternalUserGroup(
                    id="group1", user_emails=[user1.email, user2.email]
                )

            # Update the mock function
            mock_group_config.group_sync_func = updated_group_sync_func

            # Run updated sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify updated state
            updated_user_groups = _get_user_external_groups(db_session, cc_pair.id)
            updated_public_groups = _get_public_external_groups(db_session, cc_pair.id)

            assert len(updated_user_groups) == 2  # Only group1 mappings remain
            assert len(updated_public_groups) == 0  # Public group was removed

            # Verify only group1 exists
            expected_group1_id = build_ext_group_name_for_onyx(
                "group1", DocumentSource.GOOGLE_DRIVE
            )
            group_ids = {ug.external_user_group_id for ug in updated_user_groups}
            assert group_ids == {expected_group1_id}

            # Verify stale groups were actually deleted from database
            all_user_groups_including_stale = _get_user_external_groups(
                db_session, cc_pair.id, include_stale=True
            )
            all_public_groups_including_stale = _get_public_external_groups(
                db_session, cc_pair.id, include_stale=True
            )

            assert len(all_user_groups_including_stale) == 2  # Only group1 mappings
            assert len(all_public_groups_including_stale) == 0  # Public group deleted

    def test_empty_group_sync(self, db_session: Session) -> None:
        """Test syncing when no groups are returned (all groups removed)"""
        # Create test data
        user1 = create_test_user(db_session, "user1")
        cc_pair = _create_test_connector_credential_pair(db_session)

        # Initial sync with groups
        def initial_group_sync_func(
            tenant_id: str, cc_pair: ConnectorCredentialPair
        ) -> Generator[ExternalUserGroup, None, None]:
            yield ExternalUserGroup(id="group1", user_emails=[user1.email])

        with patch(
            "ee.onyx.background.celery.tasks.external_group_syncing.tasks.get_source_perm_sync_config"
        ) as mock_config:
            # Mock sync config
            mock_group_config = Mock()
            mock_group_config.group_sync_func = initial_group_sync_func

            mock_sync_config = Mock()
            mock_sync_config.group_sync_config = mock_group_config

            mock_config.return_value = mock_sync_config

            # Run initial sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify initial state
            initial_user_groups = _get_user_external_groups(db_session, cc_pair.id)
            assert len(initial_user_groups) == 1

            # Updated sync with no groups
            def empty_group_sync_func(
                tenant_id: str, cc_pair: ConnectorCredentialPair
            ) -> Generator[ExternalUserGroup, None, None]:
                # No groups yielded
                return
                yield  # This line is never reached but satisfies the generator type

            # Update the mock function
            mock_group_config.group_sync_func = empty_group_sync_func

            # Run updated sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify all groups were removed
            updated_user_groups = _get_user_external_groups(db_session, cc_pair.id)
            updated_public_groups = _get_public_external_groups(db_session, cc_pair.id)

            assert len(updated_user_groups) == 0
            assert len(updated_public_groups) == 0

    def test_batch_processing(self, db_session: Session) -> None:
        """Test that large numbers of groups are processed in batches"""
        # Create many test users
        users = []
        for i in range(150):  # More than the batch size of 100
            users.append(create_test_user(db_session, f"user{i}"))

        cc_pair = _create_test_connector_credential_pair(db_session)

        # Create a large group with many users
        def large_group_sync_func(
            tenant_id: str, cc_pair: ConnectorCredentialPair
        ) -> Generator[ExternalUserGroup, None, None]:
            yield ExternalUserGroup(
                id="large_group", user_emails=[user.email for user in users]
            )

        with patch(
            "ee.onyx.background.celery.tasks.external_group_syncing.tasks.get_source_perm_sync_config"
        ) as mock_config:
            # Mock sync config
            mock_group_config = Mock()
            mock_group_config.group_sync_func = large_group_sync_func

            mock_sync_config = Mock()
            mock_sync_config.group_sync_config = mock_group_config

            mock_config.return_value = mock_sync_config

            # Run the sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify all users were added to the group
            user_groups = _get_user_external_groups(db_session, cc_pair.id)
            assert len(user_groups) == 150

            # Verify all groups are not stale
            for ug in user_groups:
                assert ug.stale is False

    def test_mixed_regular_and_public_groups(self, db_session: Session) -> None:
        """Test syncing a mix of regular and public groups"""
        # Create test data
        user1 = create_test_user(db_session, "user1")
        user2 = create_test_user(db_session, "user2")
        cc_pair = _create_test_connector_credential_pair(db_session)

        def mixed_group_sync_func(
            tenant_id: str, cc_pair: ConnectorCredentialPair
        ) -> Generator[ExternalUserGroup, None, None]:
            yield ExternalUserGroup(
                id="regular_group", user_emails=[user1.email, user2.email]
            )
            yield ExternalUserGroup(
                id="public_group1", user_emails=[user1.email], gives_anyone_access=True
            )
            yield ExternalUserGroup(
                id="public_group2",
                user_emails=[],  # Empty user list for public group
                gives_anyone_access=True,
            )

        with patch(
            "ee.onyx.background.celery.tasks.external_group_syncing.tasks.get_source_perm_sync_config"
        ) as mock_config:
            # Mock sync config
            mock_group_config = Mock()
            mock_group_config.group_sync_func = mixed_group_sync_func

            mock_sync_config = Mock()
            mock_sync_config.group_sync_config = mock_group_config

            mock_config.return_value = mock_sync_config

            # Run the sync
            _perform_external_group_sync(cc_pair.id, TEST_TENANT_ID)

            # Verify user groups
            user_groups = _get_user_external_groups(db_session, cc_pair.id)
            expected_regular_group_id = build_ext_group_name_for_onyx(
                "regular_group", DocumentSource.GOOGLE_DRIVE
            )
            expected_public_group1_id = build_ext_group_name_for_onyx(
                "public_group1", DocumentSource.GOOGLE_DRIVE
            )

            # Should have 2 users in regular_group + 1 user in public_group1 = 3 total
            assert len(user_groups) == 3

            regular_group_users = [
                ug
                for ug in user_groups
                if ug.external_user_group_id == expected_regular_group_id
            ]
            public_group1_users = [
                ug
                for ug in user_groups
                if ug.external_user_group_id == expected_public_group1_id
            ]

            assert len(regular_group_users) == 2
            assert len(public_group1_users) == 1

            # Verify public groups
            public_groups = _get_public_external_groups(db_session, cc_pair.id)
            assert len(public_groups) == 2  # public_group1 and public_group2

            public_group_ids = {pg.external_user_group_id for pg in public_groups}
            expected_public_group2_id = build_ext_group_name_for_onyx(
                "public_group2", DocumentSource.GOOGLE_DRIVE
            )
            assert expected_public_group1_id in public_group_ids
            assert expected_public_group2_id in public_group_ids
