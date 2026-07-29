"""Guards how a user is moved onto a new address after an IdP rename.

The replaced address must survive in `prior_emails`, because it is what indexed
document ACLs still match on. Losing it here revokes access instead of bridging
it.
"""

from types import SimpleNamespace
from typing import cast

from onyx.db.models import User
from onyx.db.users import build_email_reconcile_update


def _user(email: str, prior_emails: list[str] | None = None) -> User:
    return cast(User, SimpleNamespace(email=email, prior_emails=prior_emails or []))


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
        _user("b@example.com", ["b@example.com"]), "c@example.com"
    )

    assert update is not None
    assert update["prior_emails"] == ["b@example.com"]


def test_prior_emails_list_is_rebuilt_not_mutated() -> None:
    original: list[str] = []
    user = _user("old@example.com", original)

    build_email_reconcile_update(user, "new@example.com")

    assert original == []
