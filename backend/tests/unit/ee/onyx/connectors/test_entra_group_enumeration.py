from unittest.mock import MagicMock

from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    enumerate_entra_groups,
)
from onyx.connectors.microsoft_utils.graph_client import GraphApiClient

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def test_sharepoint_entra_enumeration_uses_shared_directory_operations() -> None:
    graph_api = MagicMock(spec=GraphApiClient)
    graph_api.graph_api_base = GRAPH_BASE
    graph_api.get_json.side_effect = [
        {
            "value": [
                {"id": "known", "displayName": "Known"},
                {"id": "new", "displayName": "New"},
            ]
        },
        {
            "value": [
                {
                    "id": "user-1",
                    "userPrincipalName": "user@contoso.com",
                }
            ]
        },
    ]

    groups = list(
        enumerate_entra_groups(
            graph_api,
            already_resolved={"Known_known"},
        )
    )

    assert [(group.id, group.user_emails) for group in groups] == [
        ("New_new", ["user@contoso.com"])
    ]
    assert graph_api.get_json.call_args_list[0].args[0] == f"{GRAPH_BASE}/groups"
    assert graph_api.get_json.call_args_list[1].args[0] == (
        f"{GRAPH_BASE}/groups/new/members"
    )
