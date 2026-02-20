from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from ee.onyx.external_permissions.sharepoint.permission_utils import (
    _enumerate_ad_groups_paginated,
)
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    _iter_graph_collection,
)
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    _normalize_email,
)
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    AD_GROUP_ENUMERATION_THRESHOLD,
)
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    get_sharepoint_external_groups,
)
from ee.onyx.external_permissions.sharepoint.permission_utils import GroupsResult


MODULE = "ee.onyx.external_permissions.sharepoint.permission_utils"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_token() -> str:
    return "fake-token"


def _make_graph_page(
    items: list[dict[str, Any]],
    next_link: str | None = None,
) -> dict[str, Any]:
    page: dict[str, Any] = {"value": items}
    if next_link:
        page["@odata.nextLink"] = next_link
    return page


# ---------------------------------------------------------------------------
# _normalize_email
# ---------------------------------------------------------------------------


def test_normalize_email_strips_onmicrosoft() -> None:
    assert _normalize_email("user@contoso.onmicrosoft.com") == "user@contoso.com"


def test_normalize_email_noop_for_normal_domain() -> None:
    assert _normalize_email("user@contoso.com") == "user@contoso.com"


# ---------------------------------------------------------------------------
# _iter_graph_collection
# ---------------------------------------------------------------------------


@patch(f"{MODULE}._graph_api_get")
def test_iter_graph_collection_single_page(mock_get: MagicMock) -> None:
    mock_get.return_value = _make_graph_page([{"id": "1"}, {"id": "2"}])

    items = list(_iter_graph_collection("https://graph/items", _fake_token))
    assert items == [{"id": "1"}, {"id": "2"}]
    mock_get.assert_called_once()


@patch(f"{MODULE}._graph_api_get")
def test_iter_graph_collection_multi_page(mock_get: MagicMock) -> None:
    mock_get.side_effect = [
        _make_graph_page([{"id": "1"}], next_link="https://graph/items?page=2"),
        _make_graph_page([{"id": "2"}]),
    ]

    items = list(_iter_graph_collection("https://graph/items", _fake_token))
    assert items == [{"id": "1"}, {"id": "2"}]
    assert mock_get.call_count == 2


@patch(f"{MODULE}._graph_api_get")
def test_iter_graph_collection_empty(mock_get: MagicMock) -> None:
    mock_get.return_value = _make_graph_page([])
    assert list(_iter_graph_collection("https://graph/items", _fake_token)) == []


# ---------------------------------------------------------------------------
# _enumerate_ad_groups_paginated
# ---------------------------------------------------------------------------


def _mock_graph_get_for_enumeration(
    groups: list[dict[str, Any]],
    members_by_group: dict[str, list[dict[str, Any]]],
) -> Generator[dict[str, Any], None, None]:
    """Return a side_effect function for _graph_api_get that serves
    groups on the /groups URL and members on /groups/{id}/members URLs."""

    def side_effect(
        url: str,
        get_access_token: Any,  # noqa: ARG001
        params: dict[str, str] | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        if "/members" in url:
            group_id = url.split("/groups/")[1].split("/members")[0]
            return _make_graph_page(members_by_group.get(group_id, []))
        return _make_graph_page(groups)

    return side_effect  # type: ignore[return-value]


@patch(f"{MODULE}._graph_api_get")
def test_enumerate_ad_groups_yields_groups(mock_get: MagicMock) -> None:
    groups = [
        {"id": "g1", "displayName": "Engineering"},
        {"id": "g2", "displayName": "Marketing"},
    ]
    members = {
        "g1": [{"userPrincipalName": "alice@contoso.com"}],
        "g2": [{"mail": "bob@contoso.onmicrosoft.com"}],
    }
    mock_get.side_effect = _mock_graph_get_for_enumeration(groups, members)

    results = list(
        _enumerate_ad_groups_paginated(
            _fake_token, already_resolved=set(), graph_api_base=GRAPH_API_BASE
        )
    )

    assert len(results) == 2
    eng = next(r for r in results if r.id == "Engineering_g1")
    assert eng.user_emails == ["alice@contoso.com"]
    mkt = next(r for r in results if r.id == "Marketing_g2")
    assert mkt.user_emails == ["bob@contoso.com"]


@patch(f"{MODULE}._graph_api_get")
def test_enumerate_ad_groups_skips_already_resolved(mock_get: MagicMock) -> None:
    groups = [{"id": "g1", "displayName": "Engineering"}]
    mock_get.side_effect = _mock_graph_get_for_enumeration(groups, {})

    results = list(
        _enumerate_ad_groups_paginated(
            _fake_token,
            already_resolved={"Engineering_g1"},
            graph_api_base=GRAPH_API_BASE,
        )
    )
    assert results == []


@patch(f"{MODULE}._graph_api_get")
def test_enumerate_ad_groups_circuit_breaker(mock_get: MagicMock) -> None:
    """Enumeration stops after AD_GROUP_ENUMERATION_THRESHOLD groups."""
    over_limit = AD_GROUP_ENUMERATION_THRESHOLD + 5
    groups = [{"id": f"g{i}", "displayName": f"Group{i}"} for i in range(over_limit)]
    mock_get.side_effect = _mock_graph_get_for_enumeration(groups, {})

    results = list(
        _enumerate_ad_groups_paginated(
            _fake_token, already_resolved=set(), graph_api_base=GRAPH_API_BASE
        )
    )
    assert len(results) <= AD_GROUP_ENUMERATION_THRESHOLD


# ---------------------------------------------------------------------------
# get_sharepoint_external_groups
# ---------------------------------------------------------------------------


def _stub_role_assignment_resolution(
    groups_to_emails: dict[str, set[str]],
) -> tuple[MagicMock, MagicMock]:
    """Return (mock_sleep_and_retry, mock_recursive) pre-configured to
    simulate role-assignment group resolution."""
    mock_sleep = MagicMock()
    mock_recursive = MagicMock(
        return_value=GroupsResult(
            groups_to_emails=groups_to_emails,
            found_public_group=False,
        )
    )
    return mock_sleep, mock_recursive


@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry")
def test_default_skips_ad_enumeration(
    mock_sleep: MagicMock, mock_recursive: MagicMock  # noqa: ARG001
) -> None:
    mock_recursive.return_value = GroupsResult(
        groups_to_emails={"SiteGroup_abc": {"alice@contoso.com"}},
        found_public_group=False,
    )

    results = get_sharepoint_external_groups(
        client_context=MagicMock(),
        graph_client=MagicMock(),
        graph_api_base=GRAPH_API_BASE,
    )

    assert len(results) == 1
    assert results[0].id == "SiteGroup_abc"
    assert results[0].user_emails == ["alice@contoso.com"]


@patch(f"{MODULE}._enumerate_ad_groups_paginated")
@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry")
def test_enumerate_all_includes_ad_groups(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_recursive: MagicMock,
    mock_enum: MagicMock,
) -> None:
    from ee.onyx.db.external_perm import ExternalUserGroup

    mock_recursive.return_value = GroupsResult(
        groups_to_emails={"SiteGroup_abc": {"alice@contoso.com"}},
        found_public_group=False,
    )
    mock_enum.return_value = [
        ExternalUserGroup(id="ADGroup_xyz", user_emails=["bob@contoso.com"]),
    ]

    results = get_sharepoint_external_groups(
        client_context=MagicMock(),
        graph_client=MagicMock(),
        get_access_token=_fake_token,
        enumerate_all_ad_groups=True,
        graph_api_base=GRAPH_API_BASE,
    )

    assert len(results) == 2
    ids = {r.id for r in results}
    assert ids == {"SiteGroup_abc", "ADGroup_xyz"}
    mock_enum.assert_called_once()


@patch(f"{MODULE}._enumerate_ad_groups_paginated")
@patch(f"{MODULE}._get_groups_and_members_recursively")
@patch(f"{MODULE}.sleep_and_retry")
def test_enumerate_all_without_token_skips(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_recursive: MagicMock,
    mock_enum: MagicMock,
) -> None:
    """Even if enumerate_all_ad_groups=True, no token means skip."""
    mock_recursive.return_value = GroupsResult(
        groups_to_emails={},
        found_public_group=False,
    )

    results = get_sharepoint_external_groups(
        client_context=MagicMock(),
        graph_client=MagicMock(),
        get_access_token=None,
        enumerate_all_ad_groups=True,
        graph_api_base=GRAPH_API_BASE,
    )

    assert results == []
    mock_enum.assert_not_called()
