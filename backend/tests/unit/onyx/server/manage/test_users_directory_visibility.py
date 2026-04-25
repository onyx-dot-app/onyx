from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.db.enums import AccountType
from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.users import list_all_users_basic_info


def _fake_user(
    email: str, account_type: AccountType = AccountType.STANDARD
) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.email = email
    user.account_type = account_type
    return user


@patch("onyx.server.manage.users.USER_DIRECTORY_ADMIN_ONLY", True)
def test_list_all_users_basic_info_blocks_non_admin_when_directory_restricted() -> None:
    """With the flag on, a caller lacking READ_USERS cannot enumerate the directory."""
    user = MagicMock()
    user.effective_permissions = [Permission.BASIC_ACCESS.value]

    with pytest.raises(OnyxError) as exc_info:
        list_all_users_basic_info(
            include_api_keys=False,
            user=user,
            db_session=MagicMock(),
        )

    assert exc_info.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@patch("onyx.server.manage.users.USER_DIRECTORY_ADMIN_ONLY", True)
@patch("onyx.server.manage.users.get_all_users")
def test_list_all_users_basic_info_allows_admin_when_directory_restricted(
    mock_get_all_users: MagicMock,
) -> None:
    """With the flag on, an admin (FULL_ADMIN_PANEL_ACCESS) still gets the directory."""
    admin = MagicMock()
    admin.effective_permissions = [Permission.FULL_ADMIN_PANEL_ACCESS.value]
    mock_get_all_users.return_value = [_fake_user("a@example.com")]

    result = list_all_users_basic_info(
        include_api_keys=False,
        user=admin,
        db_session=MagicMock(),
    )

    assert [u.email for u in result] == ["a@example.com"]


@patch("onyx.server.manage.users.USER_DIRECTORY_ADMIN_ONLY", False)
@patch("onyx.server.manage.users.get_all_users")
def test_list_all_users_basic_info_allows_non_admin_when_flag_off(
    mock_get_all_users: MagicMock,
) -> None:
    """With the flag off (default), non-admin callers continue to get the directory."""
    basic = MagicMock()
    basic.effective_permissions = [Permission.BASIC_ACCESS.value]
    mock_get_all_users.return_value = [
        _fake_user("human@example.com"),
        _fake_user("bot@example.com", account_type=AccountType.BOT),
    ]

    result = list_all_users_basic_info(
        include_api_keys=False,
        user=basic,
        db_session=MagicMock(),
    )

    # BOT accounts are filtered out; human account is returned.
    assert [u.email for u in result] == ["human@example.com"]
