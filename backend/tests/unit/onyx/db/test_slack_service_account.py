from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.auth.schemas import UserRole
from onyx.configs.constants import SLACK_SERVICE_ACCOUNT_EMAIL
from onyx.db.enums import AccountType
from onyx.db.users import get_or_create_slack_service_account


def test_create_slack_service_account() -> None:
    db_session = MagicMock()
    with (
        patch("onyx.db.users.get_user_by_email", return_value=None),
        patch("onyx.db.users._generate_password_hash", return_value="hash"),
    ):
        created = get_or_create_slack_service_account(db_session)

    assert created.email == SLACK_SERVICE_ACCOUNT_EMAIL
    assert created.hashed_password == "hash"
    assert created.account_type == AccountType.SERVICE_ACCOUNT
    assert created.role == UserRole.LIMITED
    db_session.add.assert_called_once_with(created)
    db_session.commit.assert_called_once_with()


def test_reuse_slack_service_account() -> None:
    db_session = MagicMock()
    existing = MagicMock()
    with patch("onyx.db.users.get_user_by_email", return_value=existing):
        resolved = get_or_create_slack_service_account(db_session)

    assert resolved is existing
    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()
