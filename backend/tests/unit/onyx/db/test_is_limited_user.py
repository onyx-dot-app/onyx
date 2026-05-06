"""Unit tests for is_limited_user() in onyx.db.users."""

from unittest.mock import MagicMock

from onyx.db.enums import AccountType
from onyx.db.users import is_limited_user


class TestIsLimitedUser:
    def test_anonymous_user_is_limited(self) -> None:
        user = MagicMock()
        user.account_type = AccountType.ANONYMOUS
        assert is_limited_user(user) is True

    def test_service_account_no_permissions_is_limited(self) -> None:
        user = MagicMock()
        user.account_type = AccountType.SERVICE_ACCOUNT
        user.effective_permissions = []
        assert is_limited_user(user) is True

    def test_service_account_with_permissions_not_limited(self) -> None:
        user = MagicMock()
        user.account_type = AccountType.SERVICE_ACCOUNT
        user.effective_permissions = ["basic"]
        assert is_limited_user(user) is False

    def test_standard_user_not_limited(self) -> None:
        user = MagicMock()
        user.account_type = AccountType.STANDARD
        user.effective_permissions = []
        assert is_limited_user(user) is False

    def test_bot_user_not_limited(self) -> None:
        user = MagicMock()
        user.account_type = AccountType.BOT
        user.effective_permissions = []
        assert is_limited_user(user) is False

    def test_ext_perm_user_not_limited(self) -> None:
        user = MagicMock()
        user.account_type = AccountType.EXT_PERM_USER
        user.effective_permissions = []
        assert is_limited_user(user) is False
