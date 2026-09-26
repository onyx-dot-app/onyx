from unittest.mock import MagicMock

import pytest

from onyx.connectors.microsoft_utils.entra import (
    ENABLED_USERS_FILTER,
    ENTRA_GROUP_SELECT,
    ENTRA_USER_SELECT,
    EntraGroup,
    EntraUser,
    fetch_entra_page,
    fetch_entra_user,
    iter_entra_items,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


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
    page = fetch_entra_page(
        get_json,
        url=f"{GRAPH_BASE}/users",
        item_model=EntraUser,
        select_fields=ENTRA_USER_SELECT,
        page_size=5,
        filter_expression=ENABLED_USERS_FILTER,
    )
    user = fetch_entra_user(get_json, GRAPH_BASE, "mail@example.com")

    assert page.items[0].user_principal_name == "user@example.com"
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


def test_entra_group_iterator_rejects_repeated_cursor() -> None:
    get_json = MagicMock(return_value={"value": [], "@odata.nextLink": "groups-next"})

    with pytest.raises(RuntimeError, match="repeated cursor"):
        list(
            iter_entra_items(
                lambda next_link: fetch_entra_page(
                    get_json,
                    url=f"{GRAPH_BASE}/groups",
                    item_model=EntraGroup,
                    select_fields=ENTRA_GROUP_SELECT,
                    next_link=next_link,
                ),
                "Entra group listing",
            )
        )

    assert get_json.call_count == 2
