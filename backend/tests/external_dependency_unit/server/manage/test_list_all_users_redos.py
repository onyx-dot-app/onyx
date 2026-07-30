"""ReDoS regression test for the invited-user search filter in list_all_users.

The `q` search param used to be compiled as a regex and matched against every
invited email (`re.search(r"{}".format(q), email, re.I)`), so a crafted pattern
could cause catastrophic backtracking and hang API worker threads. It is now a
plain case-insensitive substring match.
"""

from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.server.manage.users import list_all_users


def test_invited_filter_is_literal_substring_not_regex(db_session: Session) -> None:
    invited = ["axb@example.com"]
    with (
        patch("onyx.server.manage.users.get_invited_users", return_value=invited),
        patch("onyx.server.manage.users.get_all_users", return_value=[]),
    ):
        # A regex metacharacter is treated literally now: "a.b" must NOT match
        # "axb@..." (it would under the old regex, where "." is any char).
        resp = list_all_users(q="a.b", db_session=db_session)
        assert [u.email for u in resp.invited] == []

        # Plain, case-insensitive substring still matches.
        resp = list_all_users(q="AXB", db_session=db_session)
        assert "axb@example.com" in [u.email for u in resp.invited]


def test_invited_filter_redos_pattern_returns_quickly(db_session: Session) -> None:
    # An email that would trigger catastrophic backtracking under the old
    # `re.search("(a+)+$", email)` code path; here it's just a literal substring.
    invited = ["a" * 40 + "@example.com"]
    with (
        patch("onyx.server.manage.users.get_invited_users", return_value=invited),
        patch("onyx.server.manage.users.get_all_users", return_value=[]),
    ):
        resp = list_all_users(q="(a+)+$", db_session=db_session)
        assert [u.email for u in resp.invited] == []
