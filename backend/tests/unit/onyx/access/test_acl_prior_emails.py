"""Guards the bridge that keeps access alive across an email change.

Query-time ACLs match on the email string, but indexed documents keep whichever
address permission sync last wrote. Including prior addresses in the user's ACL
set is what stops a renamed user losing every externally permissioned document
between the rename and the ACL rewrite. Each entry is a live grant, so the set
must also shrink back once the rewrite lands.
"""

from types import SimpleNamespace
from typing import Any, cast

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
    return _get_acl_for_user(user, cast(Any, None))


def test_current_email_alone_when_there_are_no_prior_addresses() -> None:
    assert _acl(_user("now@example.com", [])) == {
        prefix_user_email("now@example.com"),
        PUBLIC_DOC_PAT,
    }


def test_prior_address_still_grants_access() -> None:
    acl = _acl(_user("now@example.com", ["before@example.com"]))

    # The indexed documents still carry the old address, so it has to match.
    assert prefix_user_email("before@example.com") in acl
    assert prefix_user_email("now@example.com") in acl


def test_every_prior_address_is_included() -> None:
    acl = _acl(_user("c@example.com", ["a@example.com", "b@example.com"]))

    assert acl == {
        prefix_user_email("c@example.com"),
        prefix_user_email("a@example.com"),
        prefix_user_email("b@example.com"),
        PUBLIC_DOC_PAT,
    }


def test_anonymous_users_get_nothing_but_public() -> None:
    acl = _acl(_user("now@example.com", ["before@example.com"], is_anonymous=True))

    assert acl == {PUBLIC_DOC_PAT}
