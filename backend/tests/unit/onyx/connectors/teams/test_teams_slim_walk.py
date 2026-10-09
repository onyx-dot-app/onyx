"""The slim walk: what pruning and the permission sync list, and what each of
them can leave unread."""

import threading
from collections.abc import Iterator
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock, call

import pytest
import requests
from office365.teams.team import Team

from onyx.access.models import ExternalAccess
from onyx.connectors.microsoft_utils.drive_delta import SHAREPOINT_IDS_PROPERTY
from onyx.connectors.microsoft_utils.drive_items import DriveItemData
from onyx.connectors.models import Document, SlimDocument
from onyx.connectors.teams import files as files_module
from onyx.connectors.teams import listing as listing_module
from onyx.connectors.teams import sources as sources_module
from onyx.connectors.teams.connector import (
    ORGANIZER_SOURCE_TYPES,
    PREFIXED_DOCUMENT_ID_PREFIXES,
    is_thread_document_id,
)
from onyx.connectors.teams.files import FileSource, file_document_id
from onyx.connectors.teams.meeting_chats import chat_document_id
from onyx.connectors.teams.organizers import OrganizerSource
from onyx.connectors.teams.sources import SLIM_WALK, SlimWalk
from onyx.connectors.teams.transcripts import transcript_document_id
from onyx.connectors.teams.utils import DRIVE_SHAREPOINT_IDS_PROPERTY, message_delta_url
from onyx.utils.threadpool_concurrency import drain
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


def test_a_walk_with_readers_reads_channels_side_by_side_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _two_channels(monkeypatch)
    answer = client.execute_request_direct.side_effect
    both_in_flight = threading.Barrier(2, timeout=5)

    def meet(url: str) -> Any:
        if "messages/delta" in url:
            both_in_flight.wait()
        return answer(url)

    client.execute_request_direct.side_effect = meet

    assert _ids(connector(client).retrieve_all_slim_docs_perm_sync()) == {"m1", "m2"}


def test_a_walk_with_readers_gives_each_channel_its_own_rest_context_and_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """File readers come through the SDK's REST context and Graph client, both
    of which queue requests on the instance, so two channels read side by
    side must not share either."""
    _team_with_channels(monkeypatch)
    routes: dict[str, dict[str, Any]] = {}
    for n, channel_id in enumerate(CHANNELS):
        routes[_delta_url(channel_id)] = {"value": [message(f"m{n}", "one")]}
        routes[f"teams/{TEAM_ID}/channels/{channel_id}/filesFolder"] = {
            "id": f"folder-{n}",
            "parentReference": {"driveId": f"drive-{n}", "siteId": None},
        }
        routes[f"drives/drive-{n}?$select={SHAREPOINT_IDS_PROPERTY}"] = {
            DRIVE_SHAREPOINT_IDS_PROPERTY: {
                "listId": f"list-{n}",
                # One site for both, so a context cached per site alone
                # would be shared.
                "siteUrl": "https://tenant.sharepoint.example/sites/S",
            }
        }
    client = graph_client(routes)
    both_reading = threading.Barrier(2, timeout=5)
    seen: list[tuple[int, Any, Any]] = []

    def access(**kwargs: Any) -> ExternalAccess:
        # Each reader waits for the other, so readers one channel at a time
        # break the barrier.
        both_reading.wait()
        seen.append((threading.get_ident(), kwargs["ctx"], kwargs["graph_client"]))
        return ExternalAccess(
            external_user_emails=set(), external_user_group_ids=set(), is_public=False
        )

    def one_file(_client: Any, drive_id: str, **_kwargs: Any) -> Any:
        yield DriveItemData(
            id=f"file-{drive_id}",
            name="Plan.pdf",
            web_url="https://tenant.sharepoint.example/Plan.pdf",
            size=10,
            mime_type="application/pdf",
            created_datetime=datetime(2026, 9, 1, tzinfo=timezone.utc),
            last_modified_datetime=datetime(2026, 9, 2, tzinfo=timezone.utc),
            drive_id=drive_id,
        )

    monkeypatch.setattr(files_module, "iter_drive_items_paged", one_file)
    monkeypatch.setattr(files_module, "get_sharepoint_external_access", access)
    monkeypatch.setattr(
        files_module, "ClientContext", MagicMock(side_effect=lambda _: MagicMock())
    )
    monkeypatch.setattr(files_module, "acquire_token_for_rest", MagicMock())
    monkeypatch.setattr(DriveItemData, "to_sdk_driveitem", lambda self, _client: self)
    teams_connector = connector(client, include_attachments=True)
    teams_connector._acquire_token = lambda: {"access_token": "token"}

    ids = _ids(teams_connector.retrieve_all_slim_docs_perm_sync())

    assert {file_document_id("file-drive-0"), file_document_id("file-drive-1")} <= ids
    assert len(seen) == 2
    assert seen[0][0] != seen[1][0]
    assert seen[0][1] is not seen[1][1]
    assert seen[0][2] is not seen[1][2]


def test_quiet_channels_report_progress_from_their_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch of channels with nothing to list yields no document, so the
    runner's lock is renewed from the pages the workers read."""
    _team_with_channels(monkeypatch)
    client = graph_client(
        {_delta_url(CHANNELS[0]): {"value": []}, _delta_url(CHANNELS[1]): {"value": []}}
    )
    callback: MagicMock = MagicMock()
    callback.should_stop.return_value = False

    assert (
        list(connector(client).retrieve_all_slim_docs_perm_sync(callback=callback))
        == []
    )
    reports = [c.args[1] for c in callback.progress.call_args_list]
    # One report per page of every channel, besides the batch reports.
    assert reports.count(0) == 2


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
    teams_connector = connector(client)
    # One channel per batch, so the stop lands between the two channels. The
    # runner's lock lives on the progress reports.
    teams_connector.max_workers = 1
    monkeypatch.setattr("onyx.connectors.teams.connector.CHANNEL_BATCH_PER_WORKER", 1)

    with pytest.raises(RuntimeError, match="Stop signal"):
        list(teams_connector.retrieve_all_slim_docs_perm_sync(callback=callback))
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


def test_a_slow_item_holds_back_only_its_own_worker() -> None:
    """Three items, two workers: the first item waits for the third to start,
    which only happens when a worker takes the next item off the queue instead
    of the batch waiting for its slowest member."""
    third_started: threading.Event = threading.Event()

    def listing(item: str) -> Iterator[str]:
        if item == "first":
            assert third_started.wait(timeout=5), "the third item never started"
        if item == "third":
            third_started.set()
        yield item

    assert sorted(drain(["first", "second", "third"], listing, workers=2)) == [
        "first",
        "second",
        "third",
    ]


def test_a_long_batch_keeps_reporting_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    """The permission-sync lock is renewed on progress reports, so a batch
    that outlasts the lock timeout must report while it drains."""
    monkeypatch.setattr(sources_module, "PROGRESS_EVERY_DOCUMENTS", 2)
    callback: MagicMock = MagicMock()
    callback.should_stop.return_value = False
    walk: SlimWalk = SlimWalk(start=0, callback=callback, with_readers=False)

    def listing(item: int) -> Iterator[SlimDocument]:
        for n in range(3):
            yield SlimDocument(id=f"{item}-{n}", external_access=None)

    assert len(list(walk.fan_out([1, 2], listing, workers=2))) == 6
    # One report for the batch of two items, then one per two documents.
    assert (
        callback.progress.call_args_list
        == [call(SLIM_WALK, 2)] + [call(SLIM_WALK, 0)] * 3
    )


def test_quiet_listings_report_progress_from_their_pages() -> None:
    """A batch of listings that page for long and yield nothing must still
    renew the runner's lock, so each page reports from its worker, and the
    reports are serialized for a callback not built for threads."""
    callback: MagicMock = MagicMock()
    callback.should_stop.return_value = False
    walk: SlimWalk = SlimWalk(start=0, callback=callback, with_readers=False)
    reporters: set[int] = set()

    def listing(_item: int) -> Iterator[SlimDocument]:
        for _ in range(2):
            walk.page_signals()
            reporters.add(threading.get_ident())
        yield from ()

    assert list(walk.fan_out([1, 2, 3, 4], listing, workers=2, batch=4)) == []
    # One report for the batch, then one per page of every listing.
    assert (
        callback.progress.call_args_list
        == [call(SLIM_WALK, 4)] + [call(SLIM_WALK, 0)] * 8
    )
    assert threading.get_ident() not in reporters
