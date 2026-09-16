"""The Teams group sync expands the SharePoint groups of the channel sites,
and has nothing to do for a connector without attachments."""

from unittest.mock import MagicMock, patch

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.teams.group_sync import teams_group_sync

MODULE = "ee.onyx.external_permissions.teams.group_sync"
SITES = ["https://t.sharepoint.example/sites/a", "https://t.sharepoint.example/sites/b"]


def _cc_pair(include_attachments: bool) -> MagicMock:
    cc_pair = MagicMock()
    cc_pair.connector.connector_specific_config = {
        "teams": ["Engineering"],
        "include_attachments": include_attachments,
    }
    cc_pair.credential.credential_json.get_value.return_value = {"teams_client_id": "x"}
    return cc_pair


def _connector(include_attachments: bool) -> MagicMock:
    connector = MagicMock()
    connector.include_attachments = include_attachments
    connector.channel_site_urls.return_value = iter(SITES)
    connector.rest_context.side_effect = lambda url: f"ctx:{url}"
    return connector


def test_without_attachments_no_site_is_opened() -> None:
    connector = _connector(include_attachments=False)

    with (
        patch(f"{MODULE}.TeamsConnector", return_value=connector),
        patch(f"{MODULE}.get_sharepoint_external_groups") as expand,
    ):
        groups = list(teams_group_sync("tenant", _cc_pair(include_attachments=False)))

    assert groups == []
    connector.load_credentials.assert_called_once_with({"teams_client_id": "x"})
    connector.channel_site_urls.assert_not_called()
    expand.assert_not_called()


def test_each_channel_site_is_expanded_once() -> None:
    connector = _connector(include_attachments=True)
    members = ExternalUserGroup(
        id=f"{SITES[0]}::members", user_emails=["ada@example.com"]
    )
    owners = ExternalUserGroup(
        id=f"{SITES[1]}::owners", user_emails=["bob@example.com"]
    )

    with (
        patch(f"{MODULE}.TeamsConnector", return_value=connector),
        patch(
            f"{MODULE}.get_sharepoint_external_groups",
            side_effect=[[members], [owners]],
        ) as expand,
    ):
        groups = list(teams_group_sync("tenant", _cc_pair(include_attachments=True)))

    assert groups == [members, owners]
    assert [call.args[0] for call in expand.call_args_list] == [
        f"ctx:{SITES[0]}",
        f"ctx:{SITES[1]}",
    ]
