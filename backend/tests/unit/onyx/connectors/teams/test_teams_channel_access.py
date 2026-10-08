"""Channel readership: a thread names the group of its channel's members, and
the group sync names the people in it."""

from unittest.mock import MagicMock

import pytest
import requests
from office365.runtime.client_request_exception import ClientRequestException
from office365.teams.team import Team

from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.teams import listing as listing_module
from onyx.connectors.teams import utils as utils_module
from onyx.connectors.teams.models import ChannelRef
from onyx.connectors.teams.utils import (
    USER_LOOKUP_URL,
    GraphRetriesExhausted,
    UserDirectory,
    channel_access,
    channel_group_id,
    fetch_channel_member_emails,
    fetch_channel_members,
)
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL_ID,
    DELTA_URL,
    MEMBERS_URL,
    SERVICE_ROOT,
    TEAM_ID,
    connector,
    graph_client,
    member,
    message,
    replies_url,
    response,
    walk_channel,
)

STANDARD = ChannelRef(
    team_id=TEAM_ID, id=CHANNEL_ID, display_name="General", membership_type="standard"
)
PRIVATE = ChannelRef(
    team_id=TEAM_ID, id="19:private", display_name="Leads", membership_type="private"
)
TEAM_GROUP = f"teams_team-members:{TEAM_ID}".lower()
# What a checkpoint saved by an older version holds: a channel with no type.
UNTYPED = ChannelRef(team_id=TEAM_ID, id=CHANNEL_ID, display_name="General")
CHANNEL_TYPE_URL = f"teams/{TEAM_ID}/channels/{CHANNEL_ID}?$select=membershipType"


def _emails(client: MagicMock, directory: UserDirectory | None = None) -> list[str]:
    return fetch_channel_member_emails(
        client, TEAM_ID, CHANNEL_ID, directory or UserDirectory(client)
    )


def _requested(client: MagicMock) -> list[str]:
    return [call.args[0] for call in client.execute_request_direct.call_args_list]


def test_members_are_read_from_every_page_of_the_all_members_call() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {
                "value": [member("Ada", "ada@example.com", "u1")],
                "@odata.nextLink": f"{SERVICE_ROOT}/{MEMBERS_URL}?$skiptoken=p2",
            },
            f"{MEMBERS_URL}?$skiptoken=p2": {
                "value": [member("Bob", "bob@partner.example", "u2")]
            },
        }
    )

    members = fetch_channel_members(client, TEAM_ID, CHANNEL_ID)

    assert [m.email for m in members] == ["ada@example.com", "bob@partner.example"]


def test_a_teams_standard_channels_share_one_group() -> None:
    general = STANDARD
    announcements = STANDARD.model_copy(update={"id": "19:announcements"})

    # Every member of a team reads its standard channels, so one group serves
    # them all and their members are listed once.
    assert channel_group_id(general) == channel_group_id(announcements)
    assert channel_group_id(general) == f"team-members:{TEAM_ID}"


def test_a_private_channel_and_an_unknown_one_have_a_group_of_their_own() -> None:
    # A saved checkpoint can lack the membership type. It reads as unknown, and
    # the safe reading of unknown is the narrower group.
    unknown = STANDARD.model_copy(update={"membership_type": None})

    assert channel_group_id(PRIVATE) == "channel-members:19:private"
    assert channel_group_id(unknown) == f"channel-members:{CHANNEL_ID}"


def test_a_thread_names_its_group_and_no_one_by_email() -> None:
    access = channel_access(STANDARD, for_indexing=True)

    # A team of thousands would put every email on every thread, and a join or
    # a leave would rewrite them all.
    assert access.is_public is False
    assert access.external_user_emails == set()
    assert access.external_user_group_ids == {TEAM_GROUP}


def test_the_permission_sync_walk_leaves_the_source_prefix_to_the_sync() -> None:
    # The permission sync prefixes every group it is handed. A second prefix
    # (teams_teams_...) matches no synced group, and nobody can read the thread.
    access = channel_access(STANDARD, for_indexing=False)

    assert access.external_user_group_ids == {f"team-members:{TEAM_ID}"}


def test_a_member_without_an_email_is_named_by_user_id() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {"value": [member("Raunak", None, "u-raunak")]},
            USER_LOOKUP_URL: {"u-raunak": "raunak@example.com"},
        }
    )

    assert _emails(client) == ["raunak@example.com"]


def test_a_member_from_another_tenant_keeps_the_email_on_the_row() -> None:
    """Cross-tenant members of a shared channel cannot be looked up here, and
    they do not need to be: the all-members row carries their email. One whose
    row has none is not in this directory and is dropped."""
    client = graph_client(
        {
            MEMBERS_URL: {
                "value": [
                    member("Guest", "guest@other.example", "u-foreign"),
                    member("Ghost", None, "u-gone"),
                ]
            }
        }
    )

    assert _emails(client) == ["guest@other.example"]
    # Only the row without an email is asked about, and Graph does not name it.
    assert client.posted == [(USER_LOOKUP_URL, {"ids": ["u-gone"], "types": ["user"]})]


def test_one_person_spelled_two_ways_is_one_lowercase_email() -> None:
    client = graph_client(
        {
            MEMBERS_URL: {
                "value": [
                    member("Ada", "Ada@Example.com", "u1"),
                    member("Ada", None, "u2"),
                ]
            },
            USER_LOOKUP_URL: {"u2": "ada@example.com"},
        }
    )

    # The sync makes a user per distinct spelling and lowercases them after, so
    # two spellings of one new user fail the whole run on a duplicate insert.
    assert _emails(client) == ["ada@example.com"]


def test_a_refused_user_lookup_is_not_a_missing_member() -> None:
    client = graph_client(
        {MEMBERS_URL: {"value": [member("Ada", None, "u1")]}},
        refused={USER_LOOKUP_URL: 403},
    )

    with pytest.raises(requests.HTTPError):
        _emails(client)


def test_a_throttled_members_call_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK raises on a 429 instead of returning it, so the retry policy has
    to read the status off the exception."""
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    client = MagicMock()
    client.service_root_url.return_value = SERVICE_ROOT
    client.execute_request_direct.side_effect = [
        requests.HTTPError("429", response=response(429, {})),
        response(200, {"value": [member("Ada", "ada@example.com", "u1")]}),
    ]

    members = fetch_channel_members(client, TEAM_ID, CHANNEL_ID)

    assert [m.email for m in members] == ["ada@example.com"]
    assert client.execute_request_direct.call_count == 2


def test_members_without_an_email_are_named_a_batch_at_a_time_once_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A channel can hold thousands of mail-less members, so names come in
    # batches and once a run, not a request per member per channel.
    monkeypatch.setattr(utils_module, "USER_LOOKUP_BATCH_SIZE", 2)
    known = {"u1": "ada@example.com", "u2": "bob@example.com", "u3": "cy@example.com"}
    client = graph_client(
        {
            MEMBERS_URL: {"value": [member(uid, None, uid) for uid in known]},
            USER_LOOKUP_URL: known,
        }
    )
    directory = UserDirectory(client)

    for _ in range(2):
        assert _emails(client, directory) == list(known.values())

    # Two listings of the same three members: two batches, asked for once.
    assert [body["ids"] for _, body in client.posted] == [["u1", "u2"], ["u3"]]
    assert not [url for url in _requested(client) if url.startswith("users/")]


def test_an_id_graph_does_not_name_is_not_asked_for_again() -> None:
    client = graph_client(
        {MEMBERS_URL: {"value": [member("Ghost", None, "u-gone")]}, USER_LOOKUP_URL: {}}
    )
    directory = UserDirectory(client)

    for _ in range(2):
        assert _emails(client, directory) == []

    assert len(client.posted) == 1


def test_a_channel_whose_members_all_carry_an_email_asks_for_no_names() -> None:
    client = graph_client(
        {MEMBERS_URL: {"value": [member("Ada", "ada@example.com", "u1")]}}
    )

    assert _emails(client) == ["ada@example.com"]
    assert client.posted == []


def test_the_channel_walk_lists_no_members_and_names_the_thread_authors() -> None:
    client = graph_client(
        {
            DELTA_URL: {"value": [message("m1", "first"), message("m2", "second")]},
            replies_url("m1"): {"value": [message("r1", "reply", reply_to="m1")]},
            replies_url("m2"): {"value": []},
        }
    )

    items = walk_channel(connector(client), STANDARD)

    documents = [item for item in items if isinstance(item, Document)]
    assert len(documents) == 2 and len(items) == 2
    for document in documents:
        assert document.external_access == channel_access(STANDARD, for_indexing=True)
        owners = document.primary_owners or []
        assert [(o.display_name, o.email) for o in owners] == [("Ada", None)]
    # Naming a channel's people is the group sync's work, so indexing lists no
    # members, however large the team.
    assert MEMBERS_URL not in _requested(client)
    assert client.posted == []
    # The checkpoint names the channel's type, so it is not read again.
    assert CHANNEL_TYPE_URL not in _requested(client)


def test_thread_authors_are_counted_by_user_id_not_by_name() -> None:
    client = graph_client(
        {
            DELTA_URL: {"value": [message("m1", "first", sender_id="u-ada")]},
            replies_url("m1"): {
                "value": [
                    # Another person with the same name, then the first renamed.
                    message("r1", "second", reply_to="m1", sender_id="u-other"),
                    message(
                        "r2", "third", reply_to="m1", sender="Ada L", sender_id="u-ada"
                    ),
                ]
            },
        }
    )

    (document,) = walk_channel(connector(client), STANDARD)

    assert isinstance(document, Document)
    owners = [owner.display_name for owner in document.primary_owners or []]
    assert owners == ["Ada L", "Ada"]


def test_a_checkpoint_without_the_channel_type_reads_it_from_graph() -> None:
    client = graph_client(
        {
            CHANNEL_TYPE_URL: {"membershipType": "standard"},
            DELTA_URL: {"value": [message("m1", "first")]},
            replies_url("m1"): {"value": []},
        }
    )

    items = walk_channel(connector(client), UNTYPED)

    # The group sync names a standard channel's group by its team, so a resumed
    # checkpoint that named it by channel would share its threads with no one.
    assert [item.external_access for item in items if isinstance(item, Document)] == [
        channel_access(STANDARD, for_indexing=True)
    ]
    assert _requested(client).count(CHANNEL_TYPE_URL) == 1


@pytest.mark.parametrize("status", [403, 404])
def test_a_channel_whose_type_is_refused_is_one_failure_and_no_thread(
    status: int,
) -> None:
    client = graph_client(
        {
            DELTA_URL: {"value": [message("m1", "first")]},
            replies_url("m1"): {"value": []},
        },
        refused={CHANNEL_TYPE_URL: status},
    )

    items = walk_channel(connector(client), UNTYPED)

    # A guessed group could be one the group sync never lists, and its threads
    # would be shared with no one, so the channel is skipped and recorded.
    assert [type(item) for item in items] == [ConnectorFailure]
    assert DELTA_URL not in _requested(client)


def test_a_channel_type_that_cannot_be_read_yet_fails_the_step() -> None:
    client = graph_client({}, refused={CHANNEL_TYPE_URL: 401})

    # An expired token says nothing about the channel, so the step fails and
    # the checkpoint is retried.
    with pytest.raises(requests.HTTPError):
        walk_channel(connector(client), UNTYPED)


def _sdk_team(*channels: tuple[str, str]) -> tuple[MagicMock, list[MagicMock]]:
    team = MagicMock(spec=Team)
    team.id = TEAM_ID
    sdk_channels = []
    for channel_id, membership_type in channels:
        sdk_channel = MagicMock()
        sdk_channel.id = channel_id
        sdk_channel.properties = {
            "displayName": channel_id,
            "membershipType": membership_type,
        }
        sdk_channels.append(sdk_channel)
    return team, sdk_channels


def _members_url(channel_id: str) -> str:
    return f"teams/{TEAM_ID}/channels/{channel_id}/allMembers"


def test_the_group_sync_lists_a_team_once_and_each_private_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team, channels = _sdk_team(
        ("19:general", "standard"), ("19:news", "standard"), ("19:leads", "private")
    )
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: channels
    )
    client = graph_client(
        {
            _members_url("19:general"): {
                "value": [
                    member("Ada", "ada@example.com", "u1"),
                    member("Bob", None, "u2"),
                ]
            },
            _members_url("19:leads"): {
                "value": [member("Ada", "ada@example.com", "u1")]
            },
            USER_LOOKUP_URL: {"u2": "bob@example.com"},
        }
    )

    groups = dict(connector(client).channel_member_groups())

    assert groups == {
        f"team-members:{TEAM_ID}": ["ada@example.com", "bob@example.com"],
        "channel-members:19:leads": ["ada@example.com"],
    }
    # The second standard channel has the members of the first.
    assert _members_url("19:news") not in _requested(client)


def test_a_refused_channel_costs_its_own_group_and_the_listing_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team, channels = _sdk_team(
        ("19:general", "standard"), ("19:news", "standard"), ("19:leads", "private")
    )
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: channels
    )
    ada = {"value": [member("Ada", "ada@example.com", "u1")]}
    client = graph_client(
        {_members_url("19:news"): ada},
        refused={_members_url("19:general"): 403, _members_url("19:leads"): 404},
    )

    groups = dict(connector(client).channel_member_groups())

    # A raise would cost every later team its group, since the sync deletes what
    # a failed run did not reach. The team's group comes from its next standard
    # channel, and the refused private channel is the one group left out.
    assert groups == {f"team-members:{TEAM_ID}": ["ada@example.com"]}


def _refused_channel_listing(status: int) -> ClientRequestException:
    # The SDK lists channels and raises its own error type, not an HTTPError.
    resp = response(status, {})
    resp.content = b""
    return ClientRequestException(response=resp)


def test_a_refused_team_costs_its_own_groups_and_the_listing_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone, _ = _sdk_team(("19:general", "standard"))
    gone.id = "team-gone"
    team, channels = _sdk_team(("19:general", "standard"))
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [gone, team])

    def channels_of(team: MagicMock) -> list[MagicMock]:
        if team.id == "team-gone":
            raise _refused_channel_listing(404)
        return channels

    monkeypatch.setattr(listing_module, "collect_all_channels_from_team", channels_of)
    ada = {"value": [member("Ada", "ada@example.com", "u1")]}
    client = graph_client({_members_url("19:general"): ada})

    groups = dict(connector(client).channel_member_groups())

    # A team Graph lists and then refuses would otherwise end the listing, and
    # the sync deletes the groups of every team a failed run did not reach.
    assert groups == {f"team-members:{TEAM_ID}": ["ada@example.com"]}


def test_a_channel_listing_outage_fails_the_group_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team, _ = _sdk_team(("19:general", "standard"))
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])

    def channels_of(team: MagicMock) -> list[MagicMock]:  # noqa: ARG001
        raise _refused_channel_listing(503)

    monkeypatch.setattr(listing_module, "collect_all_channels_from_team", channels_of)

    with pytest.raises(ClientRequestException):
        list(connector(graph_client({})).channel_member_groups())


def test_a_transient_members_failure_fails_the_group_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    team, channels = _sdk_team(("19:general", "standard"))
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: channels
    )
    client = graph_client({}, refused={_members_url("19:general"): 503})

    # An outage says nothing about the group, so the run fails and is retried.
    with pytest.raises(GraphRetriesExhausted):
        list(connector(client).channel_member_groups())


def test_members_that_stay_throttled_fail_the_group_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    client = MagicMock()
    client.service_root_url.return_value = SERVICE_ROOT
    client.execute_request_direct.side_effect = requests.HTTPError(
        "429", response=response(429, {})
    )

    with pytest.raises(GraphRetriesExhausted):
        _emails(client)
