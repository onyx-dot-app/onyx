from unittest.mock import MagicMock

import pytest

from onyx.connectors.microsoft_utils.entra import (
    ENABLED_USERS_FILTER,
    ENTRA_GROUP_MEMBER_SELECT,
    ENTRA_GROUP_SELECT,
    ENTRA_USER_SELECT,
    EntraClient,
    EntraDirectoryObjectType,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _client(get_json: MagicMock) -> EntraClient:
    return EntraClient(get_json, GRAPH_BASE)


def test_entra_user_operations_share_models_and_query_shape() -> None:
    get_json = MagicMock(
        side_effect=[
            {
                "value": [
                    {
                        "id": "user-1",
                        "userPrincipalName": "user@example.com",
                        "accountEnabled": True,
                    }
                ],
                "@odata.nextLink": "users-next",
            },
            {
                "id": "user-2",
                "mail": "mail@example.com",
            },
        ]
    )
    client = _client(get_json)

    page = client.list_enabled_users_page(page_size=5)
    user = client.get_user("mail@example.com")

    assert page.users[0].user_principal_name == "user@example.com"
    assert page.next_link == "users-next"
    assert user.mail == "mail@example.com"
    assert get_json.call_args_list[0].args == (
        f"{GRAPH_BASE}/users",
        {
            "$select": ENTRA_USER_SELECT,
            "$top": "5",
            "$filter": ENABLED_USERS_FILTER,
        },
    )
    assert get_json.call_args_list[1].args == (
        f"{GRAPH_BASE}/users/mail@example.com",
        {"$select": ENTRA_USER_SELECT},
    )


def test_entra_group_operations_distinguish_direct_and_transitive_members() -> None:
    get_json = MagicMock(
        side_effect=[
            {
                "value": [
                    {
                        "id": "group-1",
                        "displayName": "Group",
                        "visibility": "Public",
                    }
                ]
            },
            {
                "value": [
                    {
                        "id": "user-1",
                        "@odata.type": "#microsoft.graph.user",
                        "mail": "user@example.com",
                    }
                ]
            },
            {
                "value": [
                    {
                        "id": "user-2",
                        "@odata.type": "#microsoft.graph.user",
                        "userPrincipalName": "nested@example.com",
                    }
                ]
            },
        ]
    )
    client = _client(get_json)

    group = client.list_groups_page().groups[0]
    direct = client.list_group_members_page(group_id=group.id).members[0]
    transitive = client.list_transitive_group_members_page(group_id=group.id).members[0]

    assert group.display_name == "Group"
    assert direct.odata_type == EntraDirectoryObjectType.USER
    assert transitive.user_principal_name == "nested@example.com"
    assert get_json.call_args_list[0].args == (
        f"{GRAPH_BASE}/groups",
        {"$select": ENTRA_GROUP_SELECT, "$top": "999"},
    )
    assert get_json.call_args_list[1].args == (
        f"{GRAPH_BASE}/groups/group-1/members",
        {"$select": ENTRA_GROUP_MEMBER_SELECT, "$top": "999"},
    )
    assert get_json.call_args_list[2].args == (
        f"{GRAPH_BASE}/groups/group-1/transitiveMembers",
        {"$select": ENTRA_GROUP_MEMBER_SELECT, "$top": "999"},
    )


def test_entra_group_iterator_rejects_repeated_cursor() -> None:
    get_json = MagicMock(return_value={"value": [], "@odata.nextLink": "groups-next"})
    client = _client(get_json)

    with pytest.raises(RuntimeError, match="repeated cursor"):
        list(client.iter_groups())

    assert get_json.call_count == 2
