"""Guards that a renamed user keeps matching their old address.

Indexed ACLs keep naming the address the source system knew, so matching only
the current one locks a renamed user out of their own documents until every
connector re-syncs. Treating prior addresses as the same principal is what
makes a rename invisible to search. It is safe only because the address stops
being an alias the moment another identity claims it.
"""

from types import SimpleNamespace
from typing import cast

from sqlalchemy.orm import Session

from onyx.access.access import _get_acl_for_user
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.db.models import User


def _user(email: str, prior_emails: list[str], is_anonymous: bool = False) -> User:
    return cast(
        User,
        SimpleNamespace(
            email=email, prior_emails=prior_emails, is_anonymous=is_anonymous
        ),
    )


def _acl(user: User) -> set[str]:
    return _get_acl_for_user(user, cast(Session, None))


def test_the_current_address_always_matches() -> None:
    assert _acl(_user("current@example.com", [])) == {
        prefix_user_email("current@example.com"),
        PUBLIC_DOC_PAT,
    }


def test_a_replaced_address_still_matches() -> None:
    """The rename case: documents indexed before the rename carry the old
    address and must stay reachable without waiting on a re-sync."""
    assert _acl(_user("new@example.com", ["old@example.com"])) == {
        prefix_user_email("new@example.com"),
        prefix_user_email("old@example.com"),
        PUBLIC_DOC_PAT,
    }


def test_every_address_the_user_has_held_matches() -> None:
    acl = _acl(_user("third@example.com", ["first@example.com", "second@example.com"]))

    assert acl == {
        prefix_user_email("third@example.com"),
        prefix_user_email("first@example.com"),
        prefix_user_email("second@example.com"),
        PUBLIC_DOC_PAT,
    }


def test_an_anonymous_user_gets_only_public_documents() -> None:
    """Checked before anything else, so a populated prior_emails on an
    anonymous principal cannot widen the set."""
    assert _acl(_user("anon@example.com", ["old@example.com"], is_anonymous=True)) == {
        PUBLIC_DOC_PAT
    }
