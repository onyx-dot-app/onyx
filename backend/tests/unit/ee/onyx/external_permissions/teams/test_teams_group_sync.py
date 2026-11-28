"""The Teams group sync names the members of every group a thread carries, and
with attachments on it also expands the SharePoint groups of the channel sites."""

from unittest.mock import MagicMock, patch

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.teams.group_sync import teams_group_sync
from onyx.connectors.microsoft_utils.models import EntraMember, EntraMemberKind
from tests.unit.onyx.connectors.microsoft_utils.fake_sharepoint_reader import (
    FakeSharepointReader,
)

MODULE = "ee.onyx.external_permissions.teams.group_sync"
SITES = ["https://t.sharepoint.example/sites/a", "https://t.sharepoint.example/sites/b"]
CHANNEL_GROUPS = [
    ("team-members:team-1", ["ada@example.com", "bob@example.com"]),
    ("channel-members:19:leads", ["ada@example.com"]),
]
THREAD_GROUPS = [
    ExternalUserGroup(id=group_id, user_emails=emails)
    for group_id, emails in CHANNEL_GROUPS
]


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
    connector.channel_member_groups.return_value = iter(CHANNEL_GROUPS)
    connector.permission_reader.return_value = "reader"
    return connector


def test_without_attachments_the_thread_groups_sync_and_no_site_is_opened() -> None:
    connector = _connector(include_attachments=False)

    with (
        patch(f"{MODULE}.TeamsConnector", return_value=connector),
        patch(f"{MODULE}.get_sharepoint_external_groups") as expand,
    ):
        groups = list(teams_group_sync("tenant", _cc_pair(include_attachments=False)))

    # Threads name these groups with or without attachments, and an unsynced
    # group would leave its threads readable by no one.
    assert groups == THREAD_GROUPS
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
        patch(f"{MODULE}._stored_entra_group_ids", return_value=set()),
    ):
        groups = list(teams_group_sync("tenant", _cc_pair(include_attachments=True)))

    assert groups == [*THREAD_GROUPS, members, owners]
    assert [call.args for call in expand.call_args_list] == [
        ("reader", SITES[0]),
        ("reader", SITES[1]),
    ]


SITE_GROUP_ID = "11111111-1111-1111-1111-111111111111"
FILE_GROUP_ID = "22222222-2222-2222-2222-222222222222"
NESTED_GROUP_ID = "33333333-3333-3333-3333-333333333333"


def test_entra_groups_only_files_name_are_synced() -> None:
    """A file shared with an Entra group that no site role assignment names
    would otherwise grant no one."""
    connector = _connector(include_attachments=True)
    connector.channel_site_urls.return_value = iter(SITES[:1])
    connector.permission_reader.return_value = FakeSharepointReader(
        entra_members={
            FILE_GROUP_ID: [
                EntraMember(kind=EntraMemberKind.USER, id="u1", mail="cy@example.com"),
                EntraMember(kind=EntraMemberKind.GROUP, id=NESTED_GROUP_ID),
            ],
            NESTED_GROUP_ID: [
                EntraMember(kind=EntraMemberKind.USER, id="u2", mail="di@example.com")
            ],
        }
    )
    site_group = ExternalUserGroup(id=SITE_GROUP_ID, user_emails=["ada@example.com"])
    stored_ids = {
        f"teams_{SITE_GROUP_ID}",
        f"teams_{FILE_GROUP_ID}",
        "teams_team-members:team-1",
        f"teams_{SITES[0]}::members",
    }

    with (
        patch(f"{MODULE}.TeamsConnector", return_value=connector),
        patch(f"{MODULE}.get_sharepoint_external_groups", return_value=[site_group]),
        patch(f"{MODULE}.get_session_with_current_tenant"),
        patch(
            f"{MODULE}.fetch_referenced_external_group_ids_for_cc_pair",
            return_value=stored_ids,
        ),
    ):
        groups = list(teams_group_sync("tenant", _cc_pair(include_attachments=True)))

    assert groups[: len(THREAD_GROUPS) + 1] == [*THREAD_GROUPS, site_group]
    file_only = {group.id: group.user_emails for group in groups[3:]}
    assert file_only == {
        FILE_GROUP_ID: ["cy@example.com"],
        NESTED_GROUP_ID: ["di@example.com"],
    }
