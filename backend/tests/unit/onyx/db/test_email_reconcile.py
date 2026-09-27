"""Guards how a user is moved onto a new address after an IdP rename.

The replaced address has to land in `prior_emails`, or the user loses every
document whose indexed ACL still names it until its connector re-syncs.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.enums import AccountType
from onyx.db.models import User
from onyx.db.users import (
    build_email_reconcile_update,
    reconcile_user_email__no_commit,
)


def _user(
    email: str,
    prior_emails: list[str] | None = None,
    account_type: AccountType = AccountType.STANDARD,
) -> User:
    return cast(
        User,
        SimpleNamespace(
            email=email,
            prior_emails=prior_emails if prior_emails is not None else [],
            account_type=account_type,
            oauth_accounts=[],
        ),
    )


def test_no_update_when_the_address_is_unchanged() -> None:
    assert (
        build_email_reconcile_update(_user("same@example.com"), "same@example.com")
        is None
    )


def test_case_only_difference_is_not_a_change() -> None:
    assert (
        build_email_reconcile_update(_user("User@example.com"), "user@example.com")
        is None
    )


def test_replaced_address_is_retained() -> None:
    update = build_email_reconcile_update(_user("old@example.com"), "new@example.com")

    assert update == {
        "email": "new@example.com",
        "prior_emails": ["old@example.com"],
    }


def test_earlier_addresses_are_kept_alongside() -> None:
    update = build_email_reconcile_update(
        _user("second@example.com", ["first@example.com"]), "third@example.com"
    )

    assert update is not None
    assert update["prior_emails"] == ["first@example.com", "second@example.com"]


def test_a_readopted_address_is_not_duplicated() -> None:
    update = build_email_reconcile_update(
        _user("b@example.com", ["a@example.com"]), "a@example.com"
    )

    assert update is not None
    assert update == {
        "email": "a@example.com",
        "prior_emails": ["b@example.com"],
    }


def test_new_address_is_canonicalized() -> None:
    update = build_email_reconcile_update(_user("old@example.com"), "NEW@Example.com")

    assert update is not None
    assert update["email"] == "new@example.com"


def test_prior_emails_list_is_rebuilt_not_mutated() -> None:
    original: list[str] = []
    user = _user("old@example.com", original)

    build_email_reconcile_update(user, "new@example.com")

    assert original == []


def test_reconcile_locks_and_rekeys_email_state_without_committing() -> None:
    user_id = uuid4()
    stored_user = _user("second@example.com", ["first@example.com"])
    stored_user.id = user_id
    db_session = MagicMock(spec=Session)
    query = db_session.query.return_value.filter.return_value.order_by.return_value
    query.populate_existing.return_value.with_for_update.return_value.all.return_value = [
        stored_user
    ]

    result = reconcile_user_email__no_commit(user_id, "Third@Example.com", db_session)

    assert result == (
        "second@example.com",
        ["first@example.com", "second@example.com"],
    )
    assert stored_user.email == "third@example.com"
    assert stored_user.prior_emails == ["first@example.com", "second@example.com"]
    query.populate_existing.assert_called_once_with()
    query.populate_existing.return_value.with_for_update.assert_called_once_with(
        of=User
    )
    assert db_session.execute.call_count == 2
    db_session.commit.assert_not_called()


def test_reconcile_adopts_an_external_permission_shadow() -> None:
    user_id = uuid4()
    stored_user = _user("old@example.com")
    stored_user.id = user_id
    shadow_user = _user("new@example.com", account_type=AccountType.EXT_PERM_USER)
    shadow_user.id = uuid4()
    db_session = MagicMock(spec=Session)
    query = db_session.query.return_value.filter.return_value.order_by.return_value
    query.populate_existing.return_value.with_for_update.return_value.all.return_value = [
        stored_user,
        shadow_user,
    ]

    result = reconcile_user_email__no_commit(user_id, "new@example.com", db_session)

    assert result == ("old@example.com", ["old@example.com"])
    db_session.delete.assert_called_once_with(shadow_user)
    db_session.flush.assert_called_once_with()
    assert db_session.execute.call_count == 4
