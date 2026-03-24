"""Tests for user group rename DB operation."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.db.user_group import rename_user_group
from onyx.db.models import UserGroup


class TestRenameUserGroup:
    """Tests for rename_user_group function."""

    @patch("ee.onyx.db.user_group.DISABLE_VECTOR_DB", False)
    @patch(
        "ee.onyx.db.user_group._mark_user_group__cc_pair_relationships_outdated__no_commit"
    )
    def test_rename_succeeds_and_triggers_sync(
        self, mock_mark_outdated: MagicMock
    ) -> None:
        mock_session = MagicMock()
        mock_group = MagicMock(spec=UserGroup)
        mock_group.name = "Old Name"
        mock_group.is_up_to_date = True
        mock_session.scalar.return_value = mock_group

        result = rename_user_group(mock_session, user_group_id=1, new_name="New Name")

        assert result.name == "New Name"
        assert result.is_up_to_date is False
        mock_mark_outdated.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_rename_group_not_found(self) -> None:
        mock_session = MagicMock()
        mock_session.scalar.return_value = None

        with pytest.raises(ValueError, match="not found"):
            rename_user_group(mock_session, user_group_id=999, new_name="New Name")

        mock_session.commit.assert_not_called()

    def test_rename_group_syncing_raises(self) -> None:
        mock_session = MagicMock()
        mock_group = MagicMock(spec=UserGroup)
        mock_group.is_up_to_date = False
        mock_session.scalar.return_value = mock_group

        with pytest.raises(ValueError, match="currently syncing"):
            rename_user_group(mock_session, user_group_id=1, new_name="New Name")

        mock_session.commit.assert_not_called()
