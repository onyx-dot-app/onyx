"""Thread documents: one section per message, and the checkpoint that walks a
channel one page at a time."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.models import ConnectorFailure, Document, SlimDocument
from onyx.connectors.teams.connector import TeamsCheckpoint, TeamsConnector
from onyx.connectors.teams.models import ChannelRef
from onyx.connectors.teams.utils import GraphRetriesExhausted, message_delta_url
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL,
    DELTA_URL,
    MEMBERS_URL,
    SERVICE_ROOT,
    TEAM_ID,
    channel_checkpoint,
    connector,
    graph_client,
    member,
    message,
    replies_url,
    step,
    walk_channel,
)

MEMBERS = {MEMBERS_URL: {"value": [member("Ada", "ada@example.com", "u1")]}}


def _documents(items: list[Document | ConnectorFailure]) -> list[Document]:
    assert all(isinstance(item, Document) for item in items), items
    return [item for item in items if isinstance(item, Document)]


def _only_document(routes: dict[str, dict[str, Any]]) -> Document:
    documents = _documents(walk_channel(connector(graph_client({**MEMBERS, **routes}))))
    assert len(documents) == 1
    return documents[0]


def test_a_thread_is_one_section_per_message_oldest_first() -> None:
    document = _only_document(
        {
            DELTA_URL: {
                "value": [message("m1", "Question?", created="2026-09-01T10:00:00Z")]
            },
            replies_url("m1"): {
                "value": [
                    message(
                        "r2",
                        "Second answer.",
                        reply_to="m1",
                        created="2026-09-01T12:00:00Z",
                        sender="Cy",
                    ),
                    message(
                        "r1",
                        "First answer.",
                        reply_to="m1",
                        created="2026-09-01T11:00:00Z",
                        sender="Bo",
                    ),
                ]
            },
        }
    )

    assert document.id == "m1"
    assert [section.link for section in document.sections] == [
        "https://teams.example/m1",
        "https://teams.example/r1",
        "https://teams.example/r2",
    ]
    assert [section.text for section in document.sections] == [
        "From: Ada\nDate: 2026-09-01T10:00:00+00:00\n\nQuestion?",
        "From: Bo\nDate: 2026-09-01T11:00:00+00:00\n\nFirst answer.",
        "From: Cy\nDate: 2026-09-01T12:00:00+00:00\n\nSecond answer.",
    ]
    assert document.semantic_identifier == "Ada in General about Subject m1: Question?"


def test_a_deleted_or_system_reply_leaves_no_section() -> None:
    document = _only_document(
        {
            DELTA_URL: {"value": [message("m1", "Root")]},
            replies_url("m1"): {
                "value": [
                    message(
                        "r1", "Kept", reply_to="m1", created="2026-09-01T11:00:00Z"
                    ),
                    message(
                        "r2",
                        None,
                        reply_to="m1",
                        created="2026-09-01T12:00:00Z",
                        deleted="2026-09-02T00:00:00Z",
                    ),
                    message(
                        "r3",
                        "Bo joined",
                        reply_to="m1",
                        created="2026-09-01T13:00:00Z",
                        message_type="unknownFutureValue",
                    ),
                ]
            },
        }
    )

    assert [section.link for section in document.sections] == [
        "https://teams.example/m1",
        "https://teams.example/r1",
    ]


def test_a_thread_whose_root_is_deleted_or_a_system_event_is_not_a_document() -> None:
    client = graph_client(
        {
            **MEMBERS,
            DELTA_URL: {
                "value": [
                    message("m1", None, deleted="2026-09-02T00:00:00Z"),
                    message("m2", "Channel renamed", message_type="unknownFutureValue"),
                    message("m3", "Kept"),
                ]
            },
            replies_url("m3"): {"value": []},
        }
    )

    documents = _documents(walk_channel(connector(client)))

    assert [document.id for document in documents] == ["m3"]
    requested = [call.args[0] for call in client.execute_request_direct.call_args_list]
    assert replies_url("m1") not in requested
    assert replies_url("m2") not in requested


def test_a_thread_with_no_text_is_still_a_document_so_pruning_agrees() -> None:
    """The slim walk lists every indexable root. A thread edited down to no text
    has to replace its document, or the old text would stay searchable."""
    document = _only_document(
        {
            DELTA_URL: {"value": [message("m1", None)]},
            replies_url("m1"): {
                "value": [
                    message("r1", "   ", reply_to="m1", created="2026-09-01T11:00:00Z")
                ]
            },
        }
    )

    assert document.id == "m1"
    assert [(section.link, section.text) for section in document.sections] == [
        ("https://teams.example/m1", "From: Ada\nDate: 2026-09-01T10:00:00+00:00")
    ]


def test_a_bot_post_names_an_unknown_sender() -> None:
    document = _only_document(
        {
            DELTA_URL: {"value": [message("m1", "Build passed", sender=None)]},
            replies_url("m1"): {"value": []},
        }
    )

    assert (document.sections[0].text or "").startswith("From: Unknown User\n")
    assert document.semantic_identifier.startswith("Unknown User in General")


def test_the_update_time_follows_the_latest_edit_not_the_latest_post() -> None:
    """Indexing skips a document whose update time has not moved, so an edited
    or deleted reply has to move it."""
    document = _only_document(
        {
            DELTA_URL: {
                "value": [
                    message(
                        "m1",
                        "Root",
                        created="2026-09-01T10:00:00Z",
                        modified="2026-09-05T09:00:00Z",
                    )
                ]
            },
            replies_url("m1"): {
                "value": [
                    message(
                        "r1", "Reply", reply_to="m1", created="2026-09-01T11:00:00Z"
                    )
                ]
            },
        }
    )

    assert document.doc_created_at == datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    assert document.doc_updated_at == datetime(2026, 9, 5, 9, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        pytest.param(
            message(
                "r1",
                "Edited",
                reply_to="m1",
                created="2026-09-01T11:00:00Z",
                modified="2026-09-06T08:00:00Z",
            ),
            datetime(2026, 9, 6, 8, tzinfo=timezone.utc),
            id="edited reply",
        ),
        pytest.param(
            message(
                "r1",
                None,
                reply_to="m1",
                created="2026-09-01T11:00:00Z",
                modified="2026-09-07T08:00:00Z",
                deleted="2026-09-07T08:00:00Z",
            ),
            datetime(2026, 9, 7, 8, tzinfo=timezone.utc),
            id="deleted reply",
        ),
        pytest.param(
            {
                **message("r1", "Plain", reply_to="m1", created="2026-09-03T11:00:00Z"),
                "lastModifiedDateTime": None,
            },
            datetime(2026, 9, 3, 11, tzinfo=timezone.utc),
            id="reply without a modified time falls back to its creation",
        ),
    ],
)
def test_a_reply_can_supply_the_update_time(
    reply: dict[str, Any], expected: datetime
) -> None:
    document = _only_document(
        {
            DELTA_URL: {
                "value": [message("m1", "Root", created="2026-09-01T10:00:00Z")]
            },
            replies_url("m1"): {"value": [reply]},
        }
    )

    assert document.doc_updated_at == expected


def _page(
    url: str, roots: list[dict[str, Any]], next_url: str | None
) -> dict[str, dict[str, Any]]:
    page: dict[str, Any] = {"value": roots}
    if next_url:
        page["@odata.nextLink"] = f"{SERVICE_ROOT}/{next_url}"
    return {url: page}


def test_a_step_walks_one_page_and_the_checkpoint_resumes_on_the_next() -> None:
    page_two = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=p2"
    client = graph_client(
        {
            **MEMBERS,
            **_page(DELTA_URL, [message("m1", "one")], page_two),
            **_page(page_two, [message("m2", "two")], None),
            replies_url("m1"): {"value": []},
            replies_url("m2"): {"value": []},
        }
    )
    teams_connector = connector(client)

    items, checkpoint = step(teams_connector, channel_checkpoint())
    assert [document.id for document in _documents(items)] == ["m1"]
    assert checkpoint.current_channel == CHANNEL
    assert checkpoint.next_messages_url == page_two
    assert checkpoint.has_more is True

    items, checkpoint = step(teams_connector, checkpoint)
    assert [document.id for document in _documents(items)] == ["m2"]
    assert checkpoint.current_channel is None
    assert checkpoint.next_messages_url is None
    assert checkpoint.has_more is False


def test_members_are_read_once_per_channel_per_attempt() -> None:
    """A long channel pays one members read, not one per page. The cache dies
    with the connector, so a resumed attempt (a new connector) re-reads them."""
    page_two = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=p2"
    other = ChannelRef(team_id=TEAM_ID, id="19:other@thread.tacv2", display_name="B")
    other_members = f"teams/{TEAM_ID}/channels/{other.id}/allMembers"
    client = graph_client(
        {
            **MEMBERS,
            other_members: MEMBERS[MEMBERS_URL],
            **_page(DELTA_URL, [message("m1", "one")], page_two),
            **_page(page_two, [message("m2", "two")], None),
            replies_url("m1"): {"value": []},
            replies_url("m2"): {"value": []},
            message_delta_url(TEAM_ID, other.id, 0): {"value": []},
        }
    )
    teams_connector = connector(client)
    checkpoint = TeamsCheckpoint(
        has_more=True, todo_team_ids=[], todo_channels=[other], current_channel=CHANNEL
    )

    while checkpoint.has_more:
        _, checkpoint = step(teams_connector, checkpoint)

    requested = [call.args[0] for call in client.execute_request_direct.call_args_list]
    assert requested.count(MEMBERS_URL) == 1
    assert requested.count(other_members) == 1
    assert teams_connector._channel_readers == {}

    step(connector(client), channel_checkpoint())
    requested = [call.args[0] for call in client.execute_request_direct.call_args_list]
    assert requested.count(MEMBERS_URL) == 2


def test_a_channel_that_fails_mid_walk_is_one_failure_and_the_next_channel_runs() -> (
    None
):
    other = ChannelRef(
        team_id=TEAM_ID, id="19:other@thread.tacv2", display_name="Other"
    )
    other_members = f"teams/{TEAM_ID}/channels/{other.id}/allMembers"
    page_two = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=p2"
    client = graph_client(
        {
            **MEMBERS,
            other_members: MEMBERS[MEMBERS_URL],
            **_page(DELTA_URL, [message("m1", "one")], page_two),
            replies_url("m1"): {"value": []},
            message_delta_url(TEAM_ID, other.id, 0): {
                "value": [message("o1", "other")]
            },
            replies_url("o1", other.id): {"value": []},
        },
        refused={page_two: 404},
    )
    teams_connector = connector(client)
    checkpoint = TeamsCheckpoint(
        has_more=True, todo_team_ids=[], todo_channels=[other], current_channel=CHANNEL
    )

    collected: list[Document | ConnectorFailure] = []
    while checkpoint.has_more:
        items, checkpoint = step(teams_connector, checkpoint)
        collected.extend(items)

    assert [item.id for item in collected if isinstance(item, Document)] == ["m1", "o1"]
    failures = [item for item in collected if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == CHANNEL.id


def test_a_thread_whose_replies_cannot_be_read_is_one_failure_and_the_page_goes_on() -> (
    None
):
    page_two = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=p2"
    client = graph_client(
        {
            **MEMBERS,
            **_page(DELTA_URL, [message("m1", "one"), message("m2", "two")], page_two),
            replies_url("m2"): {"value": []},
        },
        refused={replies_url("m1"): 403},
    )

    items, checkpoint = step(connector(client), channel_checkpoint())

    assert [item.id for item in items if isinstance(item, Document)] == ["m2"]
    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert len(failures) == 1
    assert failures[0].failed_entity is not None
    assert failures[0].failed_entity.entity_id == "m1"
    assert checkpoint.current_channel == CHANNEL
    assert checkpoint.next_messages_url == page_two


@pytest.mark.parametrize(
    ("refused", "raised"),
    [
        pytest.param({MEMBERS_URL: 401}, requests.HTTPError, id="expired token"),
        pytest.param({DELTA_URL: 400}, requests.HTTPError, id="rejected first page"),
        pytest.param({DELTA_URL: 429}, GraphRetriesExhausted, id="throttled page"),
        pytest.param(
            {replies_url("m1"): 503}, GraphRetriesExhausted, id="replies outage"
        ),
    ],
)
def test_a_transient_failure_fails_the_attempt_and_keeps_the_page(
    monkeypatch: pytest.MonkeyPatch,
    refused: dict[str, int],
    raised: type[Exception],
) -> None:
    """Recording these as failures would advance the checkpoint past content
    that a retry would have read."""
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    routes = {
        **MEMBERS,
        DELTA_URL: {"value": [message("m1", "one")]},
        replies_url("m1"): {"value": []},
    }
    for url in refused:
        routes.pop(url)
    client = graph_client(routes, refused=refused)
    checkpoint = channel_checkpoint()

    with pytest.raises(raised):
        step(connector(client), checkpoint)

    assert checkpoint.current_channel == CHANNEL
    assert checkpoint.next_messages_url is None


@pytest.mark.parametrize("status", [400, 410])
def test_a_saved_page_graph_rejects_restarts_the_channel_once(status: int) -> None:
    """A persisted cursor can go stale between attempts. Raising on it would
    re-request the same url every attempt, so the channel starts over instead."""
    stale = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=stale"
    client = graph_client(
        {
            **MEMBERS,
            DELTA_URL: {"value": [message("m1", "one")]},
            replies_url("m1"): {"value": []},
        },
        refused={stale: status},
    )
    teams_connector = connector(client)
    saved = TeamsCheckpoint(
        has_more=True,
        todo_team_ids=[],
        current_channel=CHANNEL,
        next_messages_url=stale,
    )

    items, checkpoint = step(teams_connector, saved)
    assert items == []
    assert checkpoint.current_channel == CHANNEL
    assert checkpoint.next_messages_url is None

    items, checkpoint = step(teams_connector, checkpoint)
    assert [document.id for document in _documents(items)] == ["m1"]
    assert checkpoint.has_more is False


def test_a_channel_restarts_once_per_attempt_and_again_on_the_next() -> None:
    """Within one attempt a second rejected page raises so the walk cannot loop.
    A new attempt (a new connector) may restart the channel again, so a
    checkpoint saved with a cursor that later went stale still recovers."""
    stale = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=stale"
    page_two = f"teams/{TEAM_ID}/channels/{CHANNEL.id}/messages/delta?$skiptoken=p2"
    client = graph_client(
        {
            **MEMBERS,
            **_page(DELTA_URL, [message("m1", "one")], page_two),
            replies_url("m1"): {"value": []},
        },
        refused={stale: 400, page_two: 400},
    )
    saved = TeamsCheckpoint(
        has_more=True,
        todo_team_ids=[],
        current_channel=CHANNEL,
        next_messages_url=stale,
    )
    first_attempt = connector(client)

    _, checkpoint = step(first_attempt, saved)
    assert checkpoint.next_messages_url is None
    items, checkpoint = step(first_attempt, checkpoint)
    assert [document.id for document in _documents(items)] == ["m1"]
    assert checkpoint.next_messages_url == page_two
    with pytest.raises(requests.HTTPError):
        step(first_attempt, checkpoint)
    assert checkpoint.next_messages_url == page_two

    _, checkpoint = step(connector(client), checkpoint)
    assert checkpoint.current_channel == CHANNEL
    assert checkpoint.next_messages_url is None


def _sdk_channel(channel_id: str, name: str) -> MagicMock:
    channel = MagicMock()
    channel.id = channel_id
    channel.properties = {"displayName": name}
    return channel


def test_the_walk_lists_teams_then_channels_then_pages_and_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = MagicMock()
    team.id = TEAM_ID
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._collect_all_teams", lambda **_: [team]
    )
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._get_team_by_id", lambda **_: team
    )
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._collect_all_channels_from_team",
        lambda **_: [
            _sdk_channel(CHANNEL.id, "General"),
            _sdk_channel("19:b@thread.tacv2", "B"),
        ],
    )
    b_delta = message_delta_url(TEAM_ID, "19:b@thread.tacv2", 0)
    client = graph_client(
        {
            **MEMBERS,
            f"teams/{TEAM_ID}/channels/19:b@thread.tacv2/allMembers": MEMBERS[
                MEMBERS_URL
            ],
            DELTA_URL: {"value": [message("m1", "one")]},
            replies_url("m1"): {"value": []},
            b_delta: {"value": []},
        }
    )
    teams_connector: TeamsConnector = connector(client)

    checkpoints: list[TeamsCheckpoint] = []
    documents: list[Document] = []
    checkpoint = teams_connector.build_dummy_checkpoint()
    while checkpoint.has_more:
        items, checkpoint = step(teams_connector, checkpoint)
        documents.extend(_documents(items))
        checkpoints.append(checkpoint)

    assert [document.id for document in documents] == ["m1"]
    assert checkpoints[0].todo_team_ids == [TEAM_ID]
    assert [channel.display_name for channel in checkpoints[1].todo_channels] == [
        "General",
        "B",
    ]
    assert checkpoints[1].todo_team_ids == []
    # Channels are popped from the end, so B is walked first.
    assert checkpoints[2].current_channel is None
    assert [channel.display_name for channel in checkpoints[2].todo_channels] == [
        "General"
    ]
    assert checkpoints[3].current_channel is None
    assert checkpoints[3].has_more is False
    assert len(checkpoints) == 4


def test_a_dummy_checkpoint_with_no_teams_ends_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._collect_all_teams", lambda **_: []
    )

    _, checkpoint = step(connector(graph_client({})), TeamsCheckpoint(has_more=True))

    assert checkpoint.todo_team_ids == []
    assert checkpoint.has_more is False


def test_a_checkpoint_saved_before_channel_cursors_existed_still_walks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = MagicMock()
    team.id = TEAM_ID
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._get_team_by_id", lambda **_: team
    )
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._collect_all_channels_from_team",
        lambda **_: [_sdk_channel(CHANNEL.id, "General")],
    )
    teams_connector = connector(
        graph_client(
            {
                **MEMBERS,
                DELTA_URL: {"value": [message("m1", "one")]},
                replies_url("m1"): {"value": []},
            }
        )
    )
    checkpoint = teams_connector.validate_checkpoint_json(
        '{"has_more": true, "todo_team_ids": ["team-1"]}'
    )

    items, checkpoint = step(teams_connector, checkpoint)
    assert checkpoint.todo_team_ids == []
    assert checkpoint.todo_channels == [CHANNEL]
    assert checkpoint.has_more is True

    documents: list[Document] = []
    for _ in range(5):
        if not checkpoint.has_more:
            break
        items, checkpoint = step(teams_connector, checkpoint)
        documents.extend(_documents(items))
    assert checkpoint.has_more is False
    assert [document.id for document in documents] == ["m1"]


def test_the_slim_walk_lists_the_same_roots_the_indexing_walk_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    team = MagicMock()
    team.id = TEAM_ID
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._collect_all_teams", lambda **_: [team]
    )
    monkeypatch.setattr(
        "onyx.connectors.teams.connector._collect_all_channels_from_team",
        lambda **_: [_sdk_channel(CHANNEL.id, "General")],
    )
    client = graph_client(
        {
            **MEMBERS,
            DELTA_URL: {
                "value": [
                    message("m1", "Kept"),
                    message("m2", None, deleted="2026-09-02T00:00:00Z"),
                    message("m3", "Renamed", message_type="unknownFutureValue"),
                ]
            },
        }
    )

    slim_ids = [
        slim.id
        for batch in connector(client).retrieve_all_slim_docs_perm_sync()
        for slim in batch
        if isinstance(slim, SlimDocument)
    ]

    assert slim_ids == ["m1"]
