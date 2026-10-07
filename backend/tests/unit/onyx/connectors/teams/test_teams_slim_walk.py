"""The slim walk: what pruning and the permission sync list, and what each of
them can leave unread."""

import threading
from datetime import date
from typing import Any
from unittest.mock import MagicMock, call

import pytest
import requests
from office365.teams.team import Team

from onyx.connectors.models import Document, SlimDocument
from onyx.connectors.teams import listing as listing_module
from onyx.connectors.teams.connector import (
    ORGANIZER_SOURCE_TYPES,
    PREFIXED_DOCUMENT_ID_PREFIXES,
    is_thread_document_id,
)
from onyx.connectors.teams.files import FileSource, file_document_id
from onyx.connectors.teams.meeting_chats import chat_document_id
from onyx.connectors.teams.organizers import OrganizerSource
from onyx.connectors.teams.sources import SLIM_WALK
from onyx.connectors.teams.transcripts import transcript_document_id
from onyx.connectors.teams.utils import message_delta_url
from tests.unit.onyx.connectors.teams.helpers import (
    CHANNEL_ID,
    TEAM_ID,
    channel_checkpoint,
    connector,
    graph_client,
    message,
    step,
)

CHANNELS = ("19:general@thread.tacv2", "19:news@thread.tacv2")


def _delta_url(channel_id: str) -> str:
    return message_delta_url(TEAM_ID, channel_id, 0)


def _team_with_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    team = MagicMock(spec=Team)
    team.id = TEAM_ID
    channels = []
    for channel_id in CHANNELS:
        channel = MagicMock()
        channel.id = channel_id
        channel.properties = {"displayName": channel_id, "membershipType": "standard"}
        channels.append(channel)
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [team])
    monkeypatch.setattr(
        listing_module, "collect_all_channels_from_team", lambda **_: channels
    )


def _ids(batches: Any) -> set[str]:
    return {
        doc.id for batch in batches for doc in batch if isinstance(doc, SlimDocument)
    }


def test_only_a_thread_has_a_bare_document_id() -> None:
    assert is_thread_document_id("1726706340932")
    assert not is_thread_document_id(file_document_id("item-1"))
    assert not is_thread_document_id(transcript_document_id("user-1", "t1"))
    assert not is_thread_document_id(
        chat_document_id("user-1", "19:meeting", date(2026, 9, 20))
    )


def test_the_permission_walk_that_leaves_threads_alone_lists_no_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed_teams = MagicMock(return_value=[])
    monkeypatch.setattr(listing_module, "collect_all_teams", listed_teams)
    client = graph_client({})
    teams_connector = connector(client)
    teams_connector.skip_threads_in_perm_sync()

    assert list(teams_connector.retrieve_all_slim_docs_perm_sync()) == []
    # A thread's readers are its channel's group for good, so with no file to
    # list there is no reason to list a team, a channel or a message.
    listed_teams.assert_not_called()
    assert client.execute_request_direct.call_args_list == []


def test_the_permission_walk_reads_threads_until_told_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    client = graph_client(
        {
            _delta_url(CHANNELS[0]): {"value": [message("m1", "one")]},
            _delta_url(CHANNELS[1]): {"value": [message("m2", "two")]},
        }
    )

    assert _ids(connector(client).retrieve_all_slim_docs_perm_sync()) == {"m1", "m2"}


def test_pruning_always_lists_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    _team_with_channels(monkeypatch)
    client = graph_client(
        {
            _delta_url(CHANNELS[0]): {"value": [message("m1", "one")]},
            _delta_url(CHANNELS[1]): {"value": [message("m2", "two")]},
        }
    )
    teams_connector = connector(client)
    teams_connector.skip_threads_in_perm_sync()

    # Pruning deletes what the walk leaves out, so it never leaves threads out.
    assert _ids(teams_connector.retrieve_all_slim_docs()) == {"m1", "m2"}


def test_pruning_lists_several_channels_at_the_same_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    client = graph_client(
        {
            _delta_url(CHANNELS[0]): {"value": [message("m1", "one")]},
            _delta_url(CHANNELS[1]): {"value": [message("m2", "two")]},
        }
    )
    answer = client.execute_request_direct.side_effect
    both_in_flight = threading.Barrier(2, timeout=5)

    def meet(url: str) -> Any:
        # Each listing waits for the other, so a walk that takes the channels
        # one at a time breaks the barrier.
        if "messages/delta" in url:
            both_in_flight.wait()
        return answer(url)

    client.execute_request_direct.side_effect = meet

    assert _ids(connector(client).retrieve_all_slim_docs()) == {"m1", "m2"}


def _two_channels(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    _team_with_channels(monkeypatch)
    return graph_client(
        {
            _delta_url(CHANNELS[0]): {"value": [message("m1", "one")]},
            _delta_url(CHANNELS[1]): {"value": [message("m2", "two")]},
        }
    )


def test_a_walk_with_readers_stays_on_the_calling_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _two_channels(monkeypatch)
    answer = client.execute_request_direct.side_effect
    threads_used: set[str] = set()

    def record(url: str) -> Any:
        threads_used.add(threading.current_thread().name)
        return answer(url)

    client.execute_request_direct.side_effect = record

    assert _ids(connector(client).retrieve_all_slim_docs_perm_sync()) == {"m1", "m2"}
    # A file's readers come from SharePoint REST, whose client is not safe
    # across threads, so a walk that reads readers takes no worker thread.
    assert threads_used == {threading.current_thread().name}


def test_a_refused_channel_fails_the_pruning_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _team_with_channels(monkeypatch)
    client = graph_client(
        {_delta_url(CHANNELS[0]): {"value": [message("m1", "one")]}},
        refused={_delta_url(CHANNELS[1]): 403},
    )

    # Pruning deletes what the walk leaves out, so a channel it could not list
    # must end the walk and never read as an empty channel.
    with pytest.raises(requests.HTTPError):
        list(connector(client).retrieve_all_slim_docs())


def test_every_batch_of_channels_reports_progress_and_honors_a_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _two_channels(monkeypatch)
    callback = MagicMock()
    callback.should_stop.side_effect = [False, True]

    # A walk with readers takes one channel per batch. The runner's lock lives
    # on the progress reports, and a stop is honored before the next channel.
    with pytest.raises(RuntimeError, match="Stop signal"):
        list(connector(client).retrieve_all_slim_docs_perm_sync(callback=callback))
    assert callback.progress.call_args_list == [call(SLIM_WALK, 1)]
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert _delta_url(CHANNELS[1]) not in requested


def test_every_source_declares_the_prefix_the_thread_check_relies_on() -> None:
    # A source whose prefix the check does not know reads as a thread, and the
    # permission sync would then stop emptying the access of its documents.
    assert set(ORGANIZER_SOURCE_TYPES) == set(OrganizerSource.__subclasses__())
    prefixes = [FileSource.document_id_prefix] + [
        source.document_id_prefix for source in ORGANIZER_SOURCE_TYPES
    ]
    assert all(prefixes)
    assert len(set(prefixes)) == len(prefixes)
    assert PREFIXED_DOCUMENT_ID_PREFIXES == tuple(prefixes)


def test_a_thread_deleted_since_the_last_poll_replaces_its_document() -> None:
    poll_start = 1_789_000_000  # 2026-09-12
    deleted = message(
        "m1",
        None,
        created="2026-09-01T10:00:00Z",
        modified="2026-09-13T09:00:00Z",
        deleted="2026-09-13T09:00:00Z",
    )
    never_indexed = message(
        "m2",
        None,
        created="2026-09-13T08:00:00Z",
        modified="2026-09-13T09:00:00Z",
        deleted="2026-09-13T09:00:00Z",
    )
    client = graph_client(
        {
            message_delta_url(TEAM_ID, CHANNEL_ID, poll_start): {
                "value": [deleted, never_indexed]
            }
        }
    )
    checkpoint = channel_checkpoint()

    items, _ = step(connector(client), checkpoint, start=poll_start)

    # The next prune can be days away and the permission sync no longer hides
    # a thread it does not list, so the deleted text leaves the index now. A
    # thread created and deleted inside the window was never indexed.
    assert [item.id for item in items if isinstance(item, Document)] == ["m1"]
    (document,) = items
    assert isinstance(document, Document)
    assert [section.text for section in document.sections] == [
        "From: Ada\nDate: 2026-09-01T10:00:00+00:00"
    ]


def test_a_first_index_writes_nothing_for_a_deleted_thread() -> None:
    deleted = message("m1", None, deleted="2026-09-13T09:00:00Z")
    client = graph_client(
        {message_delta_url(TEAM_ID, CHANNEL_ID, 0): {"value": [deleted]}}
    )

    items, _ = step(connector(client), channel_checkpoint())

    assert items == []
