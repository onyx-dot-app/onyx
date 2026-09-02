import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from ee.onyx.db.scim import ScimDAL
from onyx.db.enums import AccountType
from onyx.db.models import ScimGroupMapping, ScimToken, ScimUserMapping, User
from tests.unit.onyx.db.conftest import model_attrs


class TestScimDALTokens:
    """Tests for ScimDAL token operations."""

    def test_create_token_adds_to_session(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        user_id = uuid4()

        scim_dal.create_token(
            name="test",
            hashed_token="abc123",
            token_display="****abcd",
            created_by_id=user_id,
        )

        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()
        added_obj = mock_db_session.add.call_args[0][0]
        assert model_attrs(added_obj) == {
            "name": "test",
            "hashed_token": "abc123",
            "token_display": "****abcd",
            "created_by_id": user_id,
        }

    def test_get_token_by_hash_queries_session(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        token = ScimToken(
            id=1,
            name="test-token",
            hashed_token="a" * 64,
            token_display="onyx_scim_****abcd",
            is_active=True,
            created_by_id=uuid4(),
        )
        mock_db_session.scalar.return_value = token

        result = scim_dal.get_token_by_hash("a" * 64)

        assert result is token
        mock_db_session.scalar.assert_called_once()

    def test_revoke_token_sets_inactive(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        token = ScimToken(
            id=1,
            name="test-token",
            hashed_token="a" * 64,
            token_display="onyx_scim_****abcd",
            is_active=True,
            created_by_id=uuid4(),
        )
        mock_db_session.get.return_value = token
        expected = model_attrs(token) | {"is_active": False}

        scim_dal.revoke_token(1)

        assert model_attrs(token) == expected

    def test_revoke_nonexistent_token_raises(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            scim_dal.revoke_token(999)


class TestScimDALUserMappings:
    """Tests for ScimDAL user mapping operations."""

    def test_create_user_mapping(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        user_id = uuid4()

        scim_dal.create_user_mapping(external_id="ext-1", user_id=user_id)

        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()
        added_obj = mock_db_session.add.call_args[0][0]
        assert model_attrs(added_obj) == {
            "external_id": "ext-1",
            "user_id": user_id,
            "scim_username": None,
            "department": None,
            "manager": None,
            "given_name": None,
            "family_name": None,
            "scim_emails_json": None,
        }

    def test_delete_user_mapping(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        mapping = ScimUserMapping(id=1, external_id="ext-1", user_id=uuid4())
        mock_db_session.get.return_value = mapping

        scim_dal.delete_user_mapping(1)

        mock_db_session.delete.assert_called_once_with(mapping)

    def test_delete_nonexistent_user_mapping_is_idempotent(
        self,
        scim_dal: ScimDAL,
        mock_db_session: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_db_session.get.return_value = None

        with caplog.at_level(logging.WARNING):
            scim_dal.delete_user_mapping(999)

        mock_db_session.delete.assert_not_called()
        assert "SCIM user mapping 999 not found" in caplog.text

    def test_update_user_mapping_external_id(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        mapping = ScimUserMapping(id=1, external_id="old-id", user_id=uuid4())
        mock_db_session.get.return_value = mapping
        expected = model_attrs(mapping) | {"external_id": "new-id"}

        result = scim_dal.update_user_mapping_external_id(1, "new-id")

        assert result is mapping
        assert model_attrs(result) == expected

    def test_update_nonexistent_user_mapping_raises(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            scim_dal.update_user_mapping_external_id(999, "new-id")


class TestScimDALGroupMappings:
    """Tests for ScimDAL group mapping operations."""

    def test_create_group_mapping(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        scim_dal.create_group_mapping(external_id="ext-g1", user_group_id=5)

        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()
        added_obj = mock_db_session.add.call_args[0][0]
        assert model_attrs(added_obj) == {
            "external_id": "ext-g1",
            "user_group_id": 5,
        }

    def test_delete_group_mapping(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        mapping = ScimGroupMapping(id=1, external_id="ext-g1", user_group_id=10)
        mock_db_session.get.return_value = mapping

        scim_dal.delete_group_mapping(1)

        mock_db_session.delete.assert_called_once_with(mapping)

    def test_delete_nonexistent_group_mapping_is_idempotent(
        self,
        scim_dal: ScimDAL,
        mock_db_session: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_db_session.get.return_value = None

        with caplog.at_level(logging.WARNING):
            scim_dal.delete_group_mapping(999)

        mock_db_session.delete.assert_not_called()
        assert "SCIM group mapping 999 not found" in caplog.text


class TestScimDALUserRename:
    """A SCIM rename goes through the same reconciliation a login-driven one does.

    Rebuilding `prior_emails` from the request's own `User` snapshot loses an
    alias when two renames overlap, and it leaves the other address-keyed rows
    behind. The shared path locks and moves them.
    """

    _RECONCILE = "ee.onyx.db.scim.reconcile_user_email__no_commit"

    def test_a_rename_delegates_to_the_locking_reconcile(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        user = User(id=uuid4(), email="old@example.com")

        with patch(self._RECONCILE) as reconcile:
            scim_dal.update_user(user, email="New@Example.com")

        reconcile.assert_called_once_with(user.id, "New@Example.com", mock_db_session)

    def test_the_alias_math_is_not_reimplemented_here(
        self, scim_dal: ScimDAL, mock_db_session: MagicMock
    ) -> None:
        """A case-only change is a no-op, and deciding that is the shared path's
        job. Pre-filtering here would drift from the login path."""
        user = User(id=uuid4(), email="user@example.com", prior_emails=["old@e.com"])

        with patch(self._RECONCILE) as reconcile:
            scim_dal.update_user(user, email="User@Example.com")

        reconcile.assert_called_once_with(user.id, "User@Example.com", mock_db_session)
        assert user.prior_emails == ["old@e.com"]

    def test_updating_other_fields_never_touches_the_address(
        self, scim_dal: ScimDAL
    ) -> None:
        user = User(id=uuid4(), email="user@example.com", prior_emails=["old@e.com"])

        with patch(self._RECONCILE) as reconcile:
            scim_dal.update_user(user, is_active=False)

        reconcile.assert_not_called()
        assert user.email == "user@example.com"
        assert user.prior_emails == ["old@e.com"]


class TestScimDALPromotion:
    """Promotion is the one update that writes two fields under one flag."""

    def test_promotion_sets_standard_and_verified(self, scim_dal: ScimDAL) -> None:
        user = User(
            id=uuid4(),
            email="user@example.com",
            account_type=AccountType.EXT_PERM_USER,
            is_verified=False,
        )

        scim_dal.update_user(user, promote_to_standard=True)

        assert user.account_type == AccountType.STANDARD
        assert user.is_verified is True

    def test_other_updates_leave_promotion_fields_alone(
        self, scim_dal: ScimDAL
    ) -> None:
        user = User(
            id=uuid4(),
            email="user@example.com",
            account_type=AccountType.EXT_PERM_USER,
            is_verified=False,
        )

        scim_dal.update_user(user, is_active=True)

        assert user.account_type == AccountType.EXT_PERM_USER
        assert user.is_verified is False
