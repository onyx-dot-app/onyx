"""Unit tests for _get_user_access_info helper function.

These tests mock all database operations and don't require a real database.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.server.features.hierarchy.api import _get_user_access_info


def test_get_user_access_info_returns_email_and_groups() -> None:
    """_get_user_access_info returns the user's email and external group IDs."""
    mock_user = MagicMock()
    mock_user.email = "test@example.com"
    mock_db_session = MagicMock(spec=Session)

    with patch(
        "onyx.server.features.hierarchy.api.get_user_external_group_ids",
        return_value=["group1", "group2"],
    ):
        email, groups = _get_user_access_info(mock_user, mock_db_session)

    assert email == "test@example.com"
    assert groups == ["group1", "group2"]


def test_get_user_access_info_with_no_groups() -> None:
    """User with no external groups returns empty list."""
    mock_user = MagicMock()
    mock_user.email = "solo@example.com"
    mock_db_session = MagicMock(spec=Session)

    with patch(
        "onyx.server.features.hierarchy.api.get_user_external_group_ids",
        return_value=[],
    ):
        email, groups = _get_user_access_info(mock_user, mock_db_session)

    assert email == "solo@example.com"
    assert groups == []
