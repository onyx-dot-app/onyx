"""Who the permission-aware walk names on an issue: the team's group, the
workspace group for a public team, the parent's group too for a restricted
sub-team, and the people an issue or its ancestors are shared with."""

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from onyx.access.models import ExternalAccess
from onyx.connectors.linear.access import (
    SharedAccessIndex,
    issue_access,
    member_emails,
    workspace_members_group_id,
)
from onyx.connectors.linear.connector import LinearConnector
from onyx.connectors.linear.models import IssueShare, LinearTeam, LinearUser
from onyx.connectors.models import SlimDocument

MODULE = "onyx.connectors.linear.connector"
ORG = "org-1"

PRIVATE_PARENT = LinearTeam(id="p", key="P", visibility="private")
PUBLIC = LinearTeam(id="q", key="Q", visibility="public")
RESTRICTED = LinearTeam(id="r", key="R", visibility="restricted", parent_id="p")


def _user(email: str, **flags: bool) -> LinearUser:
    return LinearUser(
        email=email,
        active=flags.get("active", True),
        guest=flags.get("guest", False),
        app=flags.get("app", False),
    )


def test_a_private_team_names_only_itself() -> None:
    assert issue_access(PRIVATE_PARENT, ORG, set()) == ExternalAccess(
        external_user_emails=set(), external_user_group_ids={"p"}, is_public=False
    )


def test_a_public_team_adds_its_workspace_group() -> None:
    assert issue_access(PUBLIC, ORG, set()).external_user_group_ids == {
        "q",
        "workspace_members:org-1",
    }
    assert workspace_members_group_id("org-2") == "workspace_members:org-2"


def test_a_restricted_team_adds_its_private_parent() -> None:
    assert issue_access(RESTRICTED, ORG, set()).external_user_group_ids == {
        "r",
        "p",
    }


def test_a_restricted_team_without_a_parent_is_refused() -> None:
    orphan = LinearTeam(id="r", key="R", visibility="restricted")
    with pytest.raises(ValueError, match="no parent team"):
        issue_access(orphan, ORG, set())


def test_shared_emails_ride_along_as_users() -> None:
    access = issue_access(PRIVATE_PARENT, ORG, {"guest@example.com"})
    assert access.external_user_emails == {"guest@example.com"}
    assert access.is_public is False


def test_member_emails_keep_active_people_only() -> None:
    users = [
        _user(" Ann@Example.com "),
        _user("gone@example.com", active=False),
        _user("bot@example.com", app=True),
        _user("guest@partner.com", guest=True),
        _user("   "),
    ]
    assert member_emails(users) == {"ann@example.com", "guest@partner.com"}


def _no_lookup(issue_id: str) -> IssueShare:
    raise AssertionError(f"unexpected lookup of {issue_id}")


def test_an_inheriting_sub_issue_takes_its_ancestors_people() -> None:
    index = SharedAccessIndex(_no_lookup)
    index.record("root", IssueShare(parent_id=None, inherits=False, emails={"a@x"}))
    index.record("mid", IssueShare(parent_id="root", inherits=True, emails={"b@x"}))
    index.record("leaf", IssueShare(parent_id="mid", inherits=True, emails=set()))
    index.record("plain", IssueShare(parent_id=None, inherits=False, emails=set()))

    assert len(index) == 4
    assert index.emails_for("leaf") == {"a@x", "b@x"}
    assert index.emails_for("mid") == {"a@x", "b@x"}
    assert index.emails_for("root") == {"a@x"}
    assert index.emails_for("plain") == set()


def test_an_ancestor_the_walk_never_saw_is_read_on_demand_once() -> None:
    loaded: list[str] = []

    def load(issue_id: str) -> IssueShare:
        loaded.append(issue_id)
        return IssueShare(parent_id=None, inherits=False, emails={"outside@x"})

    index = SharedAccessIndex(load)
    index.record("a", IssueShare(parent_id="far", inherits=True, emails=set()))
    index.record("b", IssueShare(parent_id="far", inherits=True, emails=set()))

    assert index.emails_for("a") == {"outside@x"}
    assert index.emails_for("b") == {"outside@x"}
    assert loaded == ["far"]


def test_an_ancestor_cycle_is_refused() -> None:
    index = SharedAccessIndex(_no_lookup)
    index.record("a", IssueShare(parent_id="b", inherits=True, emails=set()))
    index.record("b", IssueShare(parent_id="a", inherits=True, emails=set()))
    with pytest.raises(ValueError, match="ancestors"):
        index.emails_for("a")


def _issue(
    issue_id: str,
    team: dict[str, Any],
    parent_id: str | None = None,
    inherits: bool = False,
    shared_with: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "inheritsSharedAccess": inherits,
        "parent": {"id": parent_id} if parent_id else None,
        "team": team,
        "sharedAccess": {
            "sharedWithUsers": [
                {"email": email, "active": True, "guest": False, "app": False}
                for email in shared_with or []
            ]
        },
    }


def _page(nodes: list[dict[str, Any]], end_cursor: str | None) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "organization": {"id": ORG},
            "issues": {
                "nodes": nodes,
                "pageInfo": {
                    "hasNextPage": end_cursor is not None,
                    "endCursor": end_cursor,
                },
            },
        }
    }
    return response


def test_the_walk_yields_inheriting_sub_issues_after_their_parents_page() -> None:
    private = {"id": "p", "key": "P", "visibility": "private", "parent": None}
    public = {"id": "q", "key": "Q", "visibility": "public", "parent": None}
    restricted = {
        "id": "r",
        "key": "R",
        "visibility": "restricted",
        "parent": {"id": "p"},
    }
    pages = [
        _page([_issue("child", private, parent_id="root", inherits=True)], "c1"),
        _page(
            [
                _issue("root", private, shared_with=["Out@Example.com"]),
                _issue("r-1", restricted),
                _issue("q-1", public),
            ],
            None,
        ),
    ]
    connector = LinearConnector()
    connector.load_credentials({"linear_api_key": "lin_api_test"})

    with patch(f"{MODULE}._make_query", side_effect=pages) as query:
        batches = [
            [cast(SlimDocument, doc) for doc in batch]
            for batch in connector.retrieve_all_slim_docs_perm_sync()
        ]

    by_id: dict[str, ExternalAccess] = {}
    for batch in batches:
        for doc in batch:
            assert doc.external_access is not None
            by_id[doc.id] = doc.external_access
    assert [[doc.id for doc in batch] for batch in batches] == [
        [],
        ["root", "r-1", "q-1"],
        ["child"],
    ]
    assert by_id["root"] == ExternalAccess(
        external_user_emails={"out@example.com"},
        external_user_group_ids={"p"},
        is_public=False,
    )
    assert by_id["child"].external_user_emails == {"out@example.com"}
    assert by_id["r-1"].external_user_group_ids == {"r", "p"}
    assert by_id["q-1"].external_user_group_ids == {"q", "workspace_members:org-1"}
    sent = [call.args[0]["variables"] for call in query.call_args_list]
    assert [v["after"] for v in sent] == [None, "c1"]
    assert all(v["first"] == 250 for v in sent)


def _share_lookup_response(errors: list[dict[str, Any]] | None) -> MagicMock:
    response = MagicMock()
    response.json.return_value = (
        {"errors": errors, "data": None}
        if errors
        else {
            "data": {
                "issue": {
                    "inheritsSharedAccess": False,
                    "parent": None,
                    "sharedAccess": {
                        "sharedWithUsers": [
                            {
                                "email": "far@x",
                                "active": True,
                                "guest": False,
                                "app": False,
                            }
                        ]
                    },
                }
            }
        }
    )
    return response


def test_a_parent_outside_the_scope_is_read_for_its_shares() -> None:
    connector = LinearConnector()
    connector.load_credentials({"linear_api_key": "lin_api_test"})

    with patch(
        f"{MODULE}._make_query", return_value=_share_lookup_response(None)
    ) as query:
        share = connector._issue_share("far")

    assert share == IssueShare(parent_id=None, inherits=False, emails={"far@x"})
    assert query.call_args.args[0]["variables"] == {"id": "far"}


def test_a_parent_the_token_cannot_see_grants_nothing() -> None:
    connector = LinearConnector()
    connector.load_credentials({"linear_api_key": "lin_api_test"})
    missing = [{"message": "Entity not found: Issue", "path": ["issue"]}]

    with patch(f"{MODULE}._make_query", return_value=_share_lookup_response(missing)):
        assert connector._issue_share("far") == IssueShare(
            parent_id=None, inherits=False, emails=set()
        )


def test_any_other_lookup_failure_fails_the_walk() -> None:
    connector = LinearConnector()
    connector.load_credentials({"linear_api_key": "lin_api_test"})
    outage = [{"message": "Rate limited", "path": ["issue"]}]

    with (
        patch(f"{MODULE}._make_query", return_value=_share_lookup_response(outage)),
        pytest.raises(RuntimeError, match="Rate limited"),
    ):
        connector._issue_share("far")
