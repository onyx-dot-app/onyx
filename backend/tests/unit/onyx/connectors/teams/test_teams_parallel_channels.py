"""The indexing step walks the active channels side by side: a page of each
per step, cursors written back only when every channel finished its page, and
a checkpoint from before the active list still resumes."""

import threading
from typing import Any

import pytest
import requests

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import Document
from onyx.connectors.teams.connector import TeamsCheckpoint, TeamsConnector
from onyx.connectors.teams.models import ChannelCursor, ChannelRef
from onyx.connectors.teams.utils import message_delta_url
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL,
    TEAM_ID,
    connector,
    graph_client,
    message,
    replies_url,
    step,
)

OTHER = ChannelRef(
    team_id=TEAM_ID,
    id="19:other@thread.tacv2",
    display_name="Other",
    membership_type="standard",
)
DELTA = message_delta_url(TEAM_ID, CHANNEL.id, 0)
OTHER_DELTA = message_delta_url(TEAM_ID, OTHER.id, 0)


def _two_channel_routes() -> dict[str, dict[str, Any]]:
    return {
        DELTA: {"value": [message("m1", "one")]},
        OTHER_DELTA: {"value": [message("o1", "other")]},
        replies_url("m1"): {"value": []},
        replies_url("o1", OTHER.id): {"value": []},
    }


def _documents(items: list[Any]) -> list[str]:
    return sorted(item.id for item in items if isinstance(item, Document))


def test_the_active_channels_are_walked_in_the_same_step() -> None:
    """The two first pages have to be in flight together or the barrier breaks."""
    client = graph_client(_two_channel_routes())
    barrier = threading.Barrier(2, timeout=5)
    answer = client.execute_request_direct.side_effect

    def gated(url: str) -> Any:
        if url in (DELTA, OTHER_DELTA):
            barrier.wait()
        return answer(url)

    client.execute_request_direct.side_effect = gated
    checkpoint = TeamsCheckpoint(
        has_more=True, todo_team_ids=[], todo_channels=[CHANNEL, OTHER]
    )

    items, checkpoint = step(connector(client), checkpoint)

    assert _documents(items) == ["m1", "o1"]
    assert checkpoint.active == []
    assert checkpoint.has_more is False


def test_a_transient_failure_in_one_channel_yields_nothing_from_the_others() -> None:
    """The other channel's page is read too, but the step raises before it
    yields a document, so the runner keeps the checkpoint it had and the
    retried step reads both pages again instead of skipping one."""
    routes = _two_channel_routes()
    routes.pop(OTHER_DELTA)
    client = graph_client(routes, refused={OTHER_DELTA: 401})
    saved = TeamsCheckpoint(
        has_more=True,
        todo_team_ids=[],
        active=[ChannelCursor(channel=CHANNEL), ChannelCursor(channel=OTHER)],
    )
    generator = connector(client).load_from_checkpoint(0, 1, saved)

    with pytest.raises(requests.HTTPError):
        next(generator)

    requested = [call.args[0] for call in client.execute_request_direct.call_args_list]
    assert DELTA in requested and OTHER_DELTA in requested


def test_a_checkpoint_from_before_the_active_list_joins_it() -> None:
    page_two = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=p2"
    client = graph_client(
        {
            DELTA: {"value": [message("m1", "one")], "@odata.nextLink": None},
            page_two: {"value": [message("m2", "two")]},
            replies_url("m1"): {"value": []},
            replies_url("m2"): {"value": []},
        }
    )
    saved = TeamsCheckpoint(
        has_more=True,
        todo_team_ids=[],
        current_channel=CHANNEL,
        next_messages_url=page_two,
    )

    items, checkpoint = step(connector(client), saved)

    assert _documents(items) == ["m2"]
    assert checkpoint.current_channel is None
    assert checkpoint.next_messages_url is None
    assert checkpoint.active == []


def test_no_more_channels_than_workers_are_active_at_once() -> None:
    third = ChannelRef(
        team_id=TEAM_ID,
        id="19:third@thread.tacv2",
        display_name="Third",
        membership_type="standard",
    )
    routes = _two_channel_routes()
    routes[message_delta_url(TEAM_ID, third.id, 0)] = {"value": []}
    teams_connector = connector(graph_client(routes))
    teams_connector.max_workers = 2
    checkpoint = TeamsCheckpoint(
        has_more=True, todo_team_ids=[], todo_channels=[CHANNEL, OTHER, third]
    )

    items, checkpoint = step(teams_connector, checkpoint)
    assert len(checkpoint.todo_channels) == 1
    assert checkpoint.active == []
    assert checkpoint.has_more is True

    more, checkpoint = step(teams_connector, checkpoint)
    assert sorted(_documents(items) + _documents(more)) == ["m1", "o1"]
    assert checkpoint.has_more is False


def test_a_non_positive_worker_count_is_rejected() -> None:
    """Zero workers would take no channel off the queue and repeat empty steps
    for ever, so the connector refuses it up front."""
    with pytest.raises(ConnectorValidationError):
        TeamsConnector(max_workers=0)
