from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from ee.onyx.db.scim import ScimDAL


class TestScimDALTokens:
    """Tests for ScimDAL token operations."""

    def test_create_token_adds_to_session(self) -> None:
        session = MagicMock()
        dal = ScimDAL(session)
        user_id = uuid4()

        dal.create_token(
            name="test",
            hashed_token="abc123",
            token_display="****abcd",
            created_by_id=user_id,
        )

        session.add.assert_called_once()
        session.flush.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert added_obj.name == "test"
        assert added_obj.hashed_token == "abc123"
        assert added_obj.created_by_id == user_id

    def test_get_token_by_hash_queries_session(self) -> None:
        session = MagicMock()
        mock_token = MagicMock()
        session.scalar.return_value = mock_token
        dal = ScimDAL(session)

        result = dal.get_token_by_hash("abc123")

        assert result is mock_token
        session.scalar.assert_called_once()

    def test_revoke_token_sets_inactive(self) -> None:
        mock_token = MagicMock()
        mock_token.is_active = True
        session = MagicMock()
        session.get.return_value = mock_token
        dal = ScimDAL(session)

        dal.revoke_token(1)

        assert mock_token.is_active is False

    def test_revoke_nonexistent_token_raises(self) -> None:
        session = MagicMock()
        session.get.return_value = None
        dal = ScimDAL(session)

        with pytest.raises(ValueError, match="not found"):
            dal.revoke_token(999)


class TestScimDALUserMappings:
    """Tests for ScimDAL user mapping operations."""

    def test_create_user_mapping(self) -> None:
        session = MagicMock()
        dal = ScimDAL(session)
        user_id = uuid4()

        dal.create_user_mapping(external_id="ext-1", user_id=user_id)

        session.add.assert_called_once()
        session.flush.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert added_obj.external_id == "ext-1"
        assert added_obj.user_id == user_id

    def test_delete_user_mapping(self) -> None:
        mock_mapping = MagicMock()
        session = MagicMock()
        session.get.return_value = mock_mapping
        dal = ScimDAL(session)

        dal.delete_user_mapping(1)

        session.delete.assert_called_once_with(mock_mapping)

    def test_delete_nonexistent_user_mapping_raises(self) -> None:
        session = MagicMock()
        session.get.return_value = None
        dal = ScimDAL(session)

        with pytest.raises(ValueError, match="not found"):
            dal.delete_user_mapping(999)

    def test_update_user_mapping_external_id(self) -> None:
        mock_mapping = MagicMock()
        mock_mapping.external_id = "old-id"
        session = MagicMock()
        session.get.return_value = mock_mapping
        dal = ScimDAL(session)

        result = dal.update_user_mapping_external_id(1, "new-id")

        assert result.external_id == "new-id"

    def test_update_nonexistent_user_mapping_raises(self) -> None:
        session = MagicMock()
        session.get.return_value = None
        dal = ScimDAL(session)

        with pytest.raises(ValueError, match="not found"):
            dal.update_user_mapping_external_id(999, "new-id")


class TestScimDALGroupMappings:
    """Tests for ScimDAL group mapping operations."""

    def test_create_group_mapping(self) -> None:
        session = MagicMock()
        dal = ScimDAL(session)

        dal.create_group_mapping(external_id="ext-g1", user_group_id=5)

        session.add.assert_called_once()
        session.flush.assert_called_once()
        added_obj = session.add.call_args[0][0]
        assert added_obj.external_id == "ext-g1"
        assert added_obj.user_group_id == 5

    def test_delete_group_mapping(self) -> None:
        mock_mapping = MagicMock()
        session = MagicMock()
        session.get.return_value = mock_mapping
        dal = ScimDAL(session)

        dal.delete_group_mapping(1)

        session.delete.assert_called_once_with(mock_mapping)

    def test_delete_nonexistent_group_mapping_raises(self) -> None:
        session = MagicMock()
        session.get.return_value = None
        dal = ScimDAL(session)

        with pytest.raises(ValueError, match="not found"):
            dal.delete_group_mapping(999)
