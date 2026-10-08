"""Channel threads through the export API: one stream per team, replies in
the stream, the channel walk as the fallback when the app lacks the approval
or a team is too large to hold."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.models import ConnectorFailure, Document
from onyx.connectors.teams import export as export_module
from onyx.connectors.teams.connector import TeamsCheckpoint, TeamsConnector
from onyx.connectors.teams.models import ChannelRef
from onyx.connectors.teams.utils import (
    GraphRetriesExhausted,
    team_export_probe_url,
    team_export_url,
)
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL,
    TEAM_ID,
    connector,
    graph_client,
    message,
    replies_url,
    requested_urls,
    step,
)

OTHER = ChannelRef(
    team_id=TEAM_ID,
    id="19:other@thread.tacv2",
    display_name="Other",
    membership_type="standard",
)
START = 1_700_000_000
PROBE = team_export_probe_url(TEAM_ID)


def _in_channel(row: dict[str, Any], channel: ChannelRef) -> dict[str, Any]:
    return {**row, "channelIdentity": {"teamId": TEAM_ID, "channelId": channel.id}}


def _sdk_channel(channel: ChannelRef) -> MagicMock:
    sdk: MagicMock = MagicMock()
    sdk.id = channel.id
    sdk.properties = {
        "displayName": channel.display_name,
        "membershipType": channel.membership_type,
    }
    return sdk


def _team_with_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "onyx.connectors.teams.listing.get_team_by_id", lambda **_: object()
    )
    monkeypatch.setattr(
        "onyx.connectors.teams.listing.collect_all_channels_from_team",
        lambda **_: [_sdk_channel(CHANNEL), _sdk_channel(OTHER)],
    )


@pytest.fixture(autouse=True)
def _clock_inside_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stream runs to the time of the request, which here never passes
    the window's end."""
    monkeypatch.setattr("onyx.connectors.teams.export.time.time", lambda: 0.0)


def _documents(items: list[Any]) -> dict[str, Document]:
    return {item.id: item for item in items if isinstance(item, Document)}


def _team_checkpoint() -> TeamsCheckpoint:
    return TeamsCheckpoint(has_more=True, todo_team_ids=[TEAM_ID])


def test_a_team_streams_whole_threads_without_a_replies_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    client: MagicMock = graph_client(
        {
            PROBE: {"value": []},
            team_export_url(TEAM_ID, 0, 1): {
                "value": [
                    _in_channel(message("m1", "one"), CHANNEL),
                    _in_channel(message("r1", "reply", reply_to="m1"), CHANNEL),
                    _in_channel(message("o1", "other"), OTHER),
                ]
            },
        }
    )

    items, checkpoint = step(connector(client), _team_checkpoint())

    documents: dict[str, Document] = _documents(items)
    assert set(documents) == {"m1", "o1"}
    assert [section.text or "" for section in documents["m1"].sections][-1].endswith(
        "reply"
    )
    assert checkpoint.export is True
    assert checkpoint.todo_team_ids == []
    assert checkpoint.has_more is False
    assert replies_url("m1") not in requested_urls(client)


def test_an_older_thread_that_only_gained_a_reply_is_read_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    old: str = "2020-01-01T10:00:00Z"
    client: MagicMock = graph_client(
        {
            PROBE: {"value": []},
            team_export_url(TEAM_ID, START, START + 1): {
                "value": [
                    _in_channel(
                        message(
                            "r9", "late", reply_to="m9", created="2026-10-01T10:00:00Z"
                        ),
                        CHANNEL,
                    )
                ]
            },
            f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/m9": message(
                "m9", "root", created=old
            ),
            replies_url("m9"): {
                "value": [
                    message(
                        "r8", "early", reply_to="m9", created="2020-01-02T10:00:00Z"
                    ),
                    message(
                        "r9", "late", reply_to="m9", created="2026-10-01T10:00:00Z"
                    ),
                ]
            },
        }
    )

    items, checkpoint = step(connector(client), _team_checkpoint(), start=START)

    documents: dict[str, Document] = _documents(items)
    assert set(documents) == {"m9"}
    assert [
        (section.text or "").split("\n")[-1] for section in documents["m9"].sections
    ] == [
        "root",
        "early",
        "late",
    ]
    assert checkpoint.export is True


def test_an_app_without_the_approval_walks_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    client: MagicMock = graph_client({}, refused={PROBE: 403})

    items, checkpoint = step(connector(client), _team_checkpoint())

    assert items == []
    assert checkpoint.export is False
    assert [channel.id for channel in checkpoint.todo_channels] == [
        CHANNEL.id,
        OTHER.id,
    ]
    assert checkpoint.todo_team_ids == []


def test_the_export_decision_is_kept_for_the_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second team step never probes again, so every step of an attempt
    takes the path the first one took."""
    _team_with_channels(monkeypatch)
    client: MagicMock = graph_client({}, refused={PROBE: 403})
    saved: TeamsCheckpoint = TeamsCheckpoint(
        has_more=True, todo_team_ids=[TEAM_ID], export=False
    )

    _, checkpoint = step(connector(client), saved)

    assert PROBE not in requested_urls(client)
    assert checkpoint.export is False


def test_a_team_too_large_to_hold_goes_to_the_channel_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    monkeypatch.setattr(export_module, "EXPORT_MESSAGES_CAP", 1)
    client: MagicMock = graph_client(
        {
            PROBE: {"value": []},
            team_export_url(TEAM_ID, 0, 1): {
                "value": [
                    _in_channel(message("m1", "one"), CHANNEL),
                    _in_channel(message("m2", "two"), CHANNEL),
                ]
            },
        }
    )

    items, checkpoint = step(connector(client), _team_checkpoint())

    assert items == []
    assert [channel.id for channel in checkpoint.todo_channels] == [
        CHANNEL.id,
        OTHER.id,
    ]
    assert checkpoint.has_more is True


def test_a_worker_lists_its_teams_channels_on_its_own_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing is an SDK query, which queues on the client it was built
    from, so four workers listing at once cannot share the direct-request
    client."""
    listing_clients: list[Any] = []

    def team_channels(graph_client: Any, _team_id: str) -> list[ChannelRef]:
        listing_clients.append(graph_client)
        return [CHANNEL]

    monkeypatch.setattr("onyx.connectors.teams.listing.team_channels", team_channels)
    client: MagicMock = graph_client(
        {PROBE: {"value": []}, team_export_url(TEAM_ID, 0, 1): {}}
    )
    teams_connector: TeamsConnector = connector(client)

    step(teams_connector, _team_checkpoint())

    assert len(listing_clients) == 1
    assert listing_clients[0] is not teams_connector.graph()


@pytest.mark.parametrize("refusal", [403, 402])
def test_a_team_whose_stream_is_refused_goes_to_the_channel_walk(
    monkeypatch: pytest.MonkeyPatch, refusal: int
) -> None:
    """One team's refusal, or a metered tenant's 402, must not fail the
    attempt: the channel walk records what each of its channels refuses, as
    it does for an app without the approval."""
    _team_with_channels(monkeypatch)
    client: MagicMock = graph_client(
        {PROBE: {"value": []}}, refused={team_export_url(TEAM_ID, 0, 1): refusal}
    )

    items, checkpoint = step(connector(client), _team_checkpoint())

    assert items == []
    assert checkpoint.export is True
    assert [channel.id for channel in checkpoint.todo_channels] == [
        CHANNEL.id,
        OTHER.id,
    ]
    assert checkpoint.has_more is True


def test_a_team_whose_stream_is_down_fails_the_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    _team_with_channels(monkeypatch)
    client: MagicMock = graph_client(
        {PROBE: {"value": []}}, refused={team_export_url(TEAM_ID, 0, 1): 503}
    )

    # An outage says nothing about the team, so the step fails and is retried.
    with pytest.raises(GraphRetriesExhausted):
        step(connector(client), _team_checkpoint())


def test_a_reply_edited_while_the_attempt_runs_is_in_the_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window's end is fixed when the attempt starts, so a stream bounded
    by it would drop a reply edited since, and the thread would lose that
    reply until the next window. The stream runs to the request's time."""
    _team_with_channels(monkeypatch)
    monkeypatch.setattr("onyx.connectors.teams.export.time.time", lambda: 1000.0)
    client: MagicMock = graph_client(
        {
            PROBE: {"value": []},
            team_export_url(TEAM_ID, 0, 1000): {
                "value": [
                    _in_channel(message("m1", "one"), CHANNEL),
                    _in_channel(message("r1", "edited", reply_to="m1"), CHANNEL),
                ]
            },
        }
    )

    items, _ = step(connector(client), _team_checkpoint())

    documents: dict[str, Document] = _documents(items)
    assert [section.text or "" for section in documents["m1"].sections][-1].endswith(
        "edited"
    )
    assert team_export_url(TEAM_ID, 0, 1) not in requested_urls(client)


def test_a_thread_in_a_channel_the_team_does_not_list_is_one_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    stranger: ChannelRef = ChannelRef(
        team_id=TEAM_ID, id="19:gone@thread.tacv2", display_name="Gone"
    )
    client: MagicMock = graph_client(
        {
            PROBE: {"value": []},
            team_export_url(TEAM_ID, 0, 1): {
                "value": [_in_channel(message("m1", "one"), stranger)]
            },
        }
    )

    items, _ = step(connector(client), _team_checkpoint())

    failures: list[ConnectorFailure] = [
        item for item in items if isinstance(item, ConnectorFailure)
    ]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "m1"
