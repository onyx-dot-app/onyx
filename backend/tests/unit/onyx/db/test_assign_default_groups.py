"""
Unit tests for assign_user_to_default_groups__no_commit in onyx.db.users.

Covers:
1. Standard/service-account users get assigned to the correct default group
2. BOT, EXT_PERM_USER, ANONYMOUS account types are skipped
3. Missing default group logs a warning and returns
4. Already-in-group is a no-op
5. IntegrityError race condition is handled gracefully
6. The function never commits the session
"""

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from onyx.db.enums import AccountType
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.users import assign_user_to_default_groups__no_commit


def _mock_user(
    account_type: AccountType = AccountType.STANDARD,
    email: str = "test@example.com",
) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.email = email
    user.account_type = account_type
    return user


def _mock_group(name: str = "Basic", group_id: int = 1) -> MagicMock:
    group = MagicMock()
    group.id = group_id
    group.name = name
    group.is_default = True
    return group


def _make_query_chain(first_return: object = None) -> MagicMock:
    """Returns a mock that supports .filter(...).filter(...).first() chaining."""
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = first_return
    return chain


def _setup_db_session(
    group_result: object = None,
    membership_result: object = None,
) -> MagicMock:
    """Create a db_session mock that routes query(UserGroup) and query(User__UserGroup)."""
    db_session = MagicMock()

    group_chain = _make_query_chain(group_result)
    membership_chain = _make_query_chain(membership_result)

    def query_side_effect(model: type) -> MagicMock:
        if model is UserGroup:
            return group_chain
        if model is User__UserGroup:
            return membership_chain
        return MagicMock()

    db_session.query.side_effect = query_side_effect
    return db_session


def test_standard_user_assigned_to_basic_group() -> None:
    group = _mock_group("Basic")
    db_session = _setup_db_session(group_result=group, membership_result=None)
    savepoint = MagicMock()
    db_session.begin_nested.return_value = savepoint
    user = _mock_user(AccountType.STANDARD)

    assign_user_to_default_groups__no_commit(db_session, user, is_admin=False)

    db_session.add.assert_called_once()
    added = db_session.add.call_args[0][0]
    assert isinstance(added, User__UserGroup)
    assert added.user_id == user.id
    assert added.user_group_id == group.id
    db_session.flush.assert_called_once()


def test_admin_user_assigned_to_admin_group() -> None:
    group = _mock_group("Admin", group_id=2)
    db_session = _setup_db_session(group_result=group, membership_result=None)
    savepoint = MagicMock()
    db_session.begin_nested.return_value = savepoint
    user = _mock_user(AccountType.STANDARD)

    assign_user_to_default_groups__no_commit(db_session, user, is_admin=True)

    db_session.add.assert_called_once()
    added = db_session.add.call_args[0][0]
    assert isinstance(added, User__UserGroup)
    assert added.user_group_id == group.id


@pytest.mark.parametrize(
    "account_type",
    [AccountType.BOT, AccountType.EXT_PERM_USER, AccountType.ANONYMOUS],
)
def test_excluded_account_types_skipped(account_type: AccountType) -> None:
    db_session = MagicMock()
    user = _mock_user(account_type)

    assign_user_to_default_groups__no_commit(db_session, user)

    db_session.query.assert_not_called()
    db_session.add.assert_not_called()


def test_service_account_not_skipped() -> None:
    group = _mock_group("Basic")
    db_session = _setup_db_session(group_result=group, membership_result=None)
    savepoint = MagicMock()
    db_session.begin_nested.return_value = savepoint
    user = _mock_user(AccountType.SERVICE_ACCOUNT)

    assign_user_to_default_groups__no_commit(db_session, user, is_admin=False)

    db_session.add.assert_called_once()


@patch("onyx.db.users.logger")
def test_missing_default_group_logs_warning(mock_logger: MagicMock) -> None:
    db_session = _setup_db_session(group_result=None)
    user = _mock_user()

    assign_user_to_default_groups__no_commit(db_session, user)

    mock_logger.warning.assert_called_once()
    warning_msg = mock_logger.warning.call_args[0][0]
    assert "No default group found" in warning_msg
    db_session.add.assert_not_called()


def test_already_in_group_is_noop() -> None:
    group = _mock_group("Basic")
    existing_membership = MagicMock()
    db_session = _setup_db_session(
        group_result=group, membership_result=existing_membership
    )
    user = _mock_user()

    assign_user_to_default_groups__no_commit(db_session, user)

    db_session.add.assert_not_called()
    db_session.begin_nested.assert_not_called()


def test_integrity_error_race_condition_handled() -> None:
    group = _mock_group("Basic")
    db_session = _setup_db_session(group_result=group, membership_result=None)
    savepoint = MagicMock()
    db_session.begin_nested.return_value = savepoint
    db_session.flush.side_effect = IntegrityError(None, None, Exception("duplicate"))
    user = _mock_user()

    # Should not raise
    assign_user_to_default_groups__no_commit(db_session, user)

    savepoint.rollback.assert_called_once()


def test_no_commit_called_on_successful_assignment() -> None:
    group = _mock_group("Basic")
    db_session = _setup_db_session(group_result=group, membership_result=None)
    savepoint = MagicMock()
    db_session.begin_nested.return_value = savepoint
    user = _mock_user()

    assign_user_to_default_groups__no_commit(db_session, user)

    db_session.commit.assert_not_called()
