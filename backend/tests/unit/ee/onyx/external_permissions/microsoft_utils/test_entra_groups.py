"""Entra group expansion and enumeration shared by the Microsoft perm-sync paths."""

from typing import Any
from unittest.mock import MagicMock, patch

from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    EntraGroup,
    enumerate_entra_groups,
    expand_entra_group,
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
            "g1": [{"userPrincipalName": "alice@contoso.com"}],
            "g2": [{"mail": "bob@contoso.onmicrosoft.com"}],
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

    assert groups == {EntraGroup(id=NESTED_GROUP_ID, name=f"Nested_{NESTED_GROUP_ID}")}
    assert user_emails == set()
