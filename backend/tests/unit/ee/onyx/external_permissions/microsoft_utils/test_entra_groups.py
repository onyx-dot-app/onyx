"""Entra group expansion and enumeration shared by the Microsoft perm-sync paths."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from office365.graph_client import GraphClient
from office365.runtime.client_request import ClientRequestException
from requests.structures import CaseInsensitiveDict

from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    ResolvedEntraGroup,
    enumerate_entra_groups,
    expand_entra_group,
    list_nested_entra_groups,
    normalize_email,
    resolve_entra_group_name,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient

MODULE = "ee.onyx.external_permissions.microsoft_utils.entra_groups"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
NESTED_GROUP_ID = "22222222-2222-2222-2222-222222222222"


class _FakeGraphClient(GraphApiClient):
    """Serve groups on /groups and members on /groups/{id}/members."""

    def __init__(
        self,
        groups: list[dict[str, Any]],
        members_by_group: dict[str, list[dict[str, Any]]],
    ) -> None:
        super().__init__(lambda: "fake-token", GRAPH_API_BASE)
        self._groups = groups
        self._members_by_group = members_by_group

    def get_json(
        self,
        url: str,
        params: dict[str, str] | None = None,  # noqa: ARG002
        headers: dict[str, str] | None = None,  # noqa: ARG002
    ) -> dict[str, Any]:
        if "/members" in url:
            group_id = url.split("/groups/")[1].split("/members")[0]
            return {"value": self._members_by_group.get(group_id, [])}
        return {"value": self._groups}


def test_normalize_email_strips_onmicrosoft() -> None:
    assert normalize_email("user@contoso.onmicrosoft.com") == "user@contoso.com"


def test_normalize_email_noop_for_normal_domain() -> None:
    assert normalize_email("user@contoso.com") == "user@contoso.com"


@patch(f"{MODULE}.find_group_id_by_name", return_value=None)
def test_unresolved_group_keeps_the_none_suffix(_mock_find: MagicMock) -> None:
    """Persisted ACLs were written with this name, so it must not change."""
    name = resolve_entra_group_name(MagicMock(), "Engineering", "Engineering")

    assert name == "Engineering_None"


def test_enumerate_yields_groups_with_normalized_members() -> None:
    client = _FakeGraphClient(
        groups=[
            {"id": "g1", "displayName": "Engineering"},
            {"id": "g2", "displayName": "Marketing"},
        ],
        members_by_group={
            "g1": [{"id": "u1", "userPrincipalName": "alice@contoso.com"}],
            "g2": [{"id": "u2", "mail": "bob@contoso.onmicrosoft.com"}],
        },
    )

    results = list(enumerate_entra_groups(client, already_resolved=set()))

    assert len(results) == 2
    eng = next(r for r in results if r.id == "Engineering_g1")
    assert eng.user_emails == ["alice@contoso.com"]
    mkt = next(r for r in results if r.id == "Marketing_g2")
    assert mkt.user_emails == ["bob@contoso.com"]


def test_enumerate_skips_already_resolved() -> None:
    client = _FakeGraphClient([{"id": "g1", "displayName": "Engineering"}], {})

    results = list(enumerate_entra_groups(client, already_resolved={"Engineering_g1"}))

    assert results == []


def test_enumerate_stops_at_threshold() -> None:
    groups = [{"id": f"g{i}", "displayName": f"Group{i}"} for i in range(5)]
    client = _FakeGraphClient(groups, {})

    results = list(enumerate_entra_groups(client, already_resolved=set(), threshold=3))

    assert [r.id for r in results] == ["Group0_g0", "Group1_g1", "Group2_g2"]


def _graph_client_with_members(members: list[MagicMock]) -> tuple[MagicMock, MagicMock]:
    page = MagicMock()
    page.current_page = members
    group = MagicMock()

    def get_all(*, page_loaded: Any) -> MagicMock:
        page_loaded(page)
        return page

    group.members.get_all.side_effect = get_all
    graph_client = MagicMock()
    graph_client.groups.__getitem__.return_value = group
    return graph_client, group


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_expand_owners_are_not_treated_as_members(_mock_sleep: MagicMock) -> None:
    member = MagicMock()
    member.to_json.return_value = {
        "userPrincipalName": "member@contoso.com",
        "mail": "member@contoso.com",
    }
    graph_client, group = _graph_client_with_members([member])
    group.owners.get_all.return_value = [MagicMock()]

    _, user_emails = expand_entra_group(
        graph_client, "11111111-1111-1111-1111-111111111111"
    )

    assert user_emails == {"member@contoso.com"}
    group.owners.get_all.assert_not_called()


@patch(f"{MODULE}.sleep_and_retry", side_effect=lambda query, _label: query)
def test_expand_names_nested_groups_for_onyx(_mock_sleep: MagicMock) -> None:
    nested = MagicMock()
    nested.to_json.return_value = {
        "id": NESTED_GROUP_ID,
        "displayName": "Nested",
        "groupTypes": [],
    }
    graph_client, _ = _graph_client_with_members([nested])

    groups, user_emails = expand_entra_group(
        graph_client, "11111111-1111-1111-1111-111111111111"
    )

    assert groups == {
        ResolvedEntraGroup(
            id=NESTED_GROUP_ID,
            name=f"Nested_{NESTED_GROUP_ID}",
        )
    }
    assert user_emails == set()


def _graph_page(body: dict[str, Any]) -> MagicMock:
    """What requests hands the SDK for one Graph page."""
    response: MagicMock = MagicMock()
    response.status_code = 200
    response.headers = CaseInsensitiveDict({"Content-Type": "application/json"})
    response.content = json.dumps(body).encode()
    response.text = json.dumps(body)
    response.json.return_value = body
    response.raise_for_status.return_value = None
    return response


def _graph_error_page(status: int, code: str) -> MagicMock:
    """A Graph refusal as the SDK sees it: raise_for_status fails."""
    response: MagicMock = _graph_page({"error": {"code": code, "message": code}})
    response.status_code = status
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


PARENT_ID = "11111111-1111-1111-1111-111111111111"
SECOND_ID = "33333333-3333-3333-3333-333333333333"
MEMBERS_URL = f"{GRAPH_API_BASE}/groups/{PARENT_ID}/members/microsoft.graph.group"
FIRST_PAGE: dict[str, Any] = {
    "value": [
        {"id": NESTED_GROUP_ID, "displayName": "Platform", "securityEnabled": True}
    ],
    "@odata.nextLink": f"{MEMBERS_URL}?$skiptoken=next",
}
SECOND_PAGE: dict[str, Any] = {
    "value": [{"id": SECOND_ID, "displayName": "Infra", "securityEnabled": True}]
}
BOTH_GROUPS: set[ResolvedEntraGroup] = {
    ResolvedEntraGroup(id=NESTED_GROUP_ID, name=f"Platform_{NESTED_GROUP_ID}"),
    ResolvedEntraGroup(id=SECOND_ID, name=f"Infra_{SECOND_ID}"),
}


def _graph_client() -> GraphClient:
    return GraphClient(lambda: {"access_token": "token", "token_type": "Bearer"})


def test_nested_groups_are_listed_through_the_group_cast() -> None:
    """Only member groups are requested and every page is read, so a large
    group's users are never paged."""
    pages: list[MagicMock] = [_graph_page(FIRST_PAGE), _graph_page(SECOND_PAGE)]

    with patch(
        "office365.runtime.client_request.requests.get", side_effect=pages
    ) as mock_get:
        groups = list_nested_entra_groups(_graph_client(), PARENT_ID)

    requested: list[str] = [call.kwargs["url"] for call in mock_get.call_args_list]
    assert requested == [
        f"{MEMBERS_URL}?$select=id,displayName,securityEnabled",
        f"{MEMBERS_URL}?$skiptoken=next",
    ]
    assert groups == BOTH_GROUPS


def test_nested_distribution_lists_are_left_out() -> None:
    """SharePoint grants nothing to a distribution list, so its members
    must not become readers through the parent group."""
    page: dict[str, Any] = {
        "value": [
            {"id": NESTED_GROUP_ID, "displayName": "Platform", "securityEnabled": True},
            {"id": SECOND_ID, "displayName": "Announce", "securityEnabled": False},
        ]
    }

    with patch(
        "office365.runtime.client_request.requests.get",
        side_effect=[_graph_page(page)],
    ):
        groups = list_nested_entra_groups(_graph_client(), PARENT_ID)

    assert groups == {
        ResolvedEntraGroup(id=NESTED_GROUP_ID, name=f"Platform_{NESTED_GROUP_ID}")
    }


def test_a_group_kind_that_cannot_nest_groups_has_none() -> None:
    """Graph documents the group cast as unsupported on Microsoft 365
    groups; that answer means no nested groups, not a failed document."""
    with patch(
        "office365.runtime.client_request.requests.get",
        side_effect=[_graph_error_page(400, "Request_UnsupportedQuery")],
    ):
        groups = list_nested_entra_groups(_graph_client(), PARENT_ID)

    assert groups == set()


def test_other_refusals_of_the_group_cast_are_raised() -> None:
    with patch(
        "office365.runtime.client_request.requests.get",
        side_effect=[_graph_error_page(403, "Authorization_RequestDenied")],
    ):
        with pytest.raises(ClientRequestException):
            list_nested_entra_groups(_graph_client(), PARENT_ID)


@patch("onyx.connectors.microsoft_utils.graph_client.time.sleep")
def test_a_retried_listing_reads_every_page(_mock_sleep: MagicMock) -> None:
    """A throttled page must not leave the group with a partial result that
    the permission cache then keeps for the whole run."""
    pages: list[MagicMock] = [
        _graph_page(FIRST_PAGE),
        _graph_error_page(429, "TooManyRequests"),
        _graph_page(FIRST_PAGE),
        _graph_page(SECOND_PAGE),
    ]

    with patch(
        "office365.runtime.client_request.requests.get", side_effect=pages
    ) as mock_get:
        groups = list_nested_entra_groups(_graph_client(), PARENT_ID)

    assert mock_get.call_count == 4
    assert groups == BOTH_GROUPS
