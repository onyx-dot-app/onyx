"""Meeting chats: a day of a scheduled meeting's chat is a document, walked
through the meeting's organizer and readable by the members who see that day."""

from datetime import date
from typing import Any

import pytest
import requests

from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    ImageSection,
    SlimDocument,
)
from onyx.connectors.teams import images as images_module
from onyx.connectors.teams import listing as listing_module
from onyx.connectors.teams import meeting_chats as meeting_chats_module
from onyx.connectors.teams.connector import TeamsCheckpoint, TeamsConnector
from onyx.connectors.teams.meeting_chats import (
    CHATS_QUERY,
    chat_document_id,
    fetch_chat_days,
)
from onyx.connectors.teams.utils import USER_LOOKUP_URL, GraphRetriesExhausted
from tests.unit.onyx.connectors.teams.helpers import (
    SERVICE_ROOT,
    Refusal,
    connector,
    graph_client,
    message,
    step,
)

ORGANIZERS_URL = (
    "users?$select=id,userPrincipalName,mail,displayName"
    "&$filter=accountEnabled eq true and assignedPlans/any("
    "p:p/service eq 'TeamspaceAPI' and p/capabilityStatus eq 'Enabled')"
    "&$count=true&$top=100"
)
ADA = {"id": "user-1", "userPrincipalName": "ada@example.com", "mail": None}
# The clock every test runs at.
NOW = 1_789_997_600  # 2026-09-21T13:33:20Z
CHAT = "19:meeting_abc@thread.v2"
CHAT_URL = "https://teams.example/chat/abc"
CHATS_URL = f"users/user-1/chats?{CHATS_QUERY}"
MEMBERS_URL = f"chats/{CHAT}/members"
ALL_MESSAGES_URL = f"chats/{CHAT}/messages?$top=50&$orderby=createdDateTime desc"
WHOLE_CHAT = "0001-01-01T00:00:00Z"
PLAIN_403: Refusal = (403, "Forbidden", "Missing role permissions on the request.")


@pytest.fixture(autouse=True)
def _frozen_clock_and_no_teams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: float(NOW))
    # The slim walk lists the teams first, through the SDK.
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [])


def _chat(
    chat_id: str = CHAT,
    organizer: str | None = "user-1",
    last_message: str | None = "2026-09-20T18:59:00Z",
    topic: str | None = "Launch review",
) -> dict[str, Any]:
    return {
        "id": chat_id,
        "topic": topic,
        "chatType": "meeting",
        "webUrl": CHAT_URL,
        "onlineMeetingInfo": {"organizer": {"id": organizer}} if organizer else None,
        "lastMessagePreview": (
            {"createdDateTime": last_message} if last_message else None
        ),
    }


def _said(message_id: str, text: str | None, created: str, **kwargs: Any) -> dict:
    # Graph gives a chat message no url of its own.
    return {**message(message_id, text, created=created, **kwargs), "webUrl": None}


def _event(message_id: str, created: str) -> dict:
    return _said(
        message_id, None, created, message_type="unknownFutureValue", sender=None
    )


def _member(
    email: str | None, user_id: str, sees_from: str = WHOLE_CHAT
) -> dict[str, Any]:
    return {
        "displayName": user_id,
        "email": email,
        "userId": user_id,
        "visibleHistoryStartDateTime": sees_from,
    }


def _routes(*messages: dict, members: list[dict] | None = None) -> dict[str, Any]:
    return {
        ORGANIZERS_URL: {"value": [ADA]},
        CHATS_URL: {"value": [_chat()]},
        MEMBERS_URL: {"value": members or [_member("ada@example.com", "user-1")]},
        # Graph serves the newest message first.
        ALL_MESSAGES_URL: {"value": list(messages)},
    }


def _walk(
    teams_connector: TeamsConnector, start: int = 0
) -> list[Document | ConnectorFailure]:
    checkpoint = TeamsCheckpoint(has_more=True, todo_team_ids=[])
    items: list[Document | ConnectorFailure] = []
    while checkpoint.has_more:
        page, checkpoint = step(teams_connector, checkpoint, start=start)
        items.extend(page)
    return items


def _requested(client: Any) -> list[str]:
    return [call.args[0] for call in client.execute_request_direct.call_args_list]


def _validate_organizers(teams_connector: TeamsConnector) -> None:
    assert teams_connector._organizers is not None
    teams_connector._organizers.validate()


def test_meeting_chats_are_off_by_default() -> None:
    client = graph_client(_routes())

    assert _walk(connector(client)) == []
    assert _requested(client) == []


def test_a_day_of_a_meeting_chat_is_one_document() -> None:
    client = graph_client(
        _routes(
            _said("m3", "See you next week", "2026-09-20T19:05:00Z", sender="Bob"),
            _event("e2", "2026-09-20T19:01:00Z"),
            _said("m2", "Ship it on Friday", "2026-09-20T18:59:00Z"),
            _event("e1", "2026-09-20T18:55:00Z"),
        )
    )

    items = _walk(connector(client, include_meeting_chats=True))

    assert len(items) == 1 and isinstance(items[0], Document)
    document = items[0]
    assert document.id == f"teams-chat:user-1:{CHAT}:2026-09-20"
    assert document.id == chat_document_id("user-1", CHAT, date(2026, 9, 20))
    assert document.semantic_identifier == "Chat of Launch review (2026-09-20)"
    # Oldest first, what people wrote and none of the meeting's own events.
    texts = [section.text or "" for section in document.sections]
    assert ["Ship it on Friday" in texts[0], "See you next week" in texts[1]] == [
        True,
        True,
    ]
    assert len(texts) == 2
    assert {section.link for section in document.sections} == {CHAT_URL}
    assert [o.display_name for o in document.primary_owners or []] == ["Ada", "Bob"]
    assert document.external_access is not None
    assert document.external_access.external_user_emails == {"ada@example.com"}
    assert document.external_access.is_public is False


def test_each_day_is_its_own_document() -> None:
    client = graph_client(
        _routes(
            _said("m2", "Follow up", "2026-09-21T09:00:00Z"),
            _said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"),
        )
    )

    items = _walk(connector(client, include_meeting_chats=True))

    # Graph serves the chat newest first, and a day is written as soon as an
    # older one begins.
    assert [item.id for item in items if isinstance(item, Document)] == [
        f"teams-chat:user-1:{CHAT}:2026-09-21",
        f"teams-chat:user-1:{CHAT}:2026-09-20",
    ]


def test_a_day_is_written_before_the_next_page_of_the_chat_is_read() -> None:
    next_page = f"chats/{CHAT}/messages?$skiptoken=p2"
    routes = _routes(
        _said("m3", "Follow up", "2026-09-21T09:00:00Z"),
        _said("m2", "Kickoff notes", "2026-09-20T18:59:00Z"),
    )
    routes[ALL_MESSAGES_URL] = {
        **routes[ALL_MESSAGES_URL],
        "@odata.nextLink": f"{SERVICE_ROOT}/{next_page}",
    }
    routes[next_page] = {"value": [_said("m1", "Agenda", "2026-09-19T10:00:00Z")]}
    client = graph_client(routes)

    days = fetch_chat_days(client, CHAT, None)
    first_day, _ = next(days)

    # A day is complete once an older one begins, so a busy chat holds one day
    # in memory, not six months of it.
    assert first_day.isoformat() == "2026-09-21"
    assert next_page not in _requested(client)
    assert [day.isoformat() for day, _ in days] == ["2026-09-20", "2026-09-19"]


def test_a_day_of_events_alone_is_no_document() -> None:
    client = graph_client(_routes(_event("e1", "2026-09-20T18:55:00Z")))

    assert _walk(connector(client, include_meeting_chats=True)) == []


def test_a_member_added_later_does_not_read_the_days_before() -> None:
    members = [
        _member("ada@example.com", "user-1"),
        _member("late@example.com", "user-2", sees_from="2026-09-21T08:00:00Z"),
        # Joined a minute into the first day, after its first message.
        _member("mid@example.com", "user-3", sees_from="2026-09-20T19:00:00Z"),
    ]
    client = graph_client(
        _routes(
            _said("m2", "Follow up", "2026-09-21T09:00:00Z"),
            _said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"),
            members=members,
        )
    )

    items = _walk(connector(client, include_meeting_chats=True))

    readers = {
        item.id[-10:]: item.external_access.external_user_emails
        for item in items
        if isinstance(item, Document) and item.external_access is not None
    }
    # Teams shows a member the chat from when they were added, so a day is read
    # by those who see its first message and the whole of it.
    assert readers == {
        "2026-09-20": {"ada@example.com"},
        "2026-09-21": {"ada@example.com", "late@example.com", "mid@example.com"},
    }


@pytest.mark.parametrize("walk", ["indexing", "permission sync"])
@pytest.mark.parametrize("first_deleted", [None, "2026-09-25T10:00:00Z"])
def test_a_days_readers_come_from_its_first_message(
    walk: str, first_deleted: str | None
) -> None:
    members = [
        _member("ada@example.com", "user-1"),
        # Added between the day's two messages, so part of the day is hidden.
        _member("mid@example.com", "user-3", sees_from="2026-09-20T19:00:00Z"),
    ]
    # A delete is seen at the next poll and the text is indexed until then, so
    # readers taken from the next message would let in someone who never saw it.
    client = graph_client(
        _routes(
            _said("m2", "Second", "2026-09-20T19:30:00Z"),
            _said("m1", "First", "2026-09-20T18:59:00Z", deleted=first_deleted),
            members=members,
        )
    )
    teams_connector = connector(client, include_meeting_chats=True)

    if walk == "indexing":
        accesses = [
            item.external_access
            for item in _walk(teams_connector)
            if isinstance(item, Document)
        ]
    else:
        accesses = [
            doc.external_access
            for batch in teams_connector.retrieve_all_slim_docs_perm_sync()
            for doc in batch
            if isinstance(doc, SlimDocument)
        ]

    assert [a.external_user_emails for a in accesses if a] == [{"ada@example.com"}]


def test_a_sender_graph_does_not_name_does_not_stop_the_walk() -> None:
    nameless = _said("m1", "Kickoff notes", "2026-09-20T18:59:00Z")
    nameless["from"]["user"]["displayName"] = None
    client = graph_client(_routes(nameless))

    items = _walk(connector(client, include_meeting_chats=True))

    assert len(items) == 1 and isinstance(items[0], Document)
    assert "Unknown User" in (items[0].sections[0].text or "")


def test_an_edit_moves_the_documents_update_time() -> None:
    client = graph_client(
        _routes(
            _said(
                "m1",
                "Kickoff notes, fixed",
                "2026-09-20T18:59:00Z",
                modified="2026-09-21T09:00:00Z",
            )
        )
    )

    items = _walk(connector(client, include_meeting_chats=True))

    # Indexing skips a document whose update time has not moved.
    assert isinstance(items[0], Document) and items[0].doc_updated_at is not None
    assert items[0].doc_updated_at.isoformat() == "2026-09-21T09:00:00+00:00"


def test_a_first_index_keeps_whole_days_inside_the_lookback() -> None:
    # The lookback opens at 13:33 on 2026-03-22. That day is cut, so it is left
    # out whole: a cut day would take its readers from a later message.
    client = graph_client(
        _routes(
            _said("m3", "Inside", "2026-03-23T08:00:00Z"),
            _said("m2", "Edge day, after the cut", "2026-03-22T20:00:00Z"),
            _said("m1", "Edge day, before the cut", "2026-03-22T09:00:00Z"),
        )
    )

    items = _walk(connector(client, include_meeting_chats=True))

    assert [item.id[-10:] for item in items if isinstance(item, Document)] == [
        "2026-03-23"
    ]


def test_a_member_without_an_email_is_named_through_the_directory() -> None:
    routes = _routes(
        _said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"),
        members=[_member(None, "user-9")],
    )
    routes[USER_LOOKUP_URL] = {"user-9": "nine@example.com"}
    client = graph_client(routes)

    items = _walk(connector(client, include_meeting_chats=True))

    assert isinstance(items[0], Document) and items[0].external_access is not None
    assert items[0].external_access.external_user_emails == {"nine@example.com"}


def test_a_chat_is_walked_through_its_organizer_alone() -> None:
    routes = _routes()
    routes[CHATS_URL] = {"value": [_chat(organizer="someone-else")]}
    client = graph_client(routes)

    # Every member lists the same chat, so it is read where its organizer is
    # walked. Graph refuses the chat of a meeting another tenant set up.
    assert _walk(connector(client, include_meeting_chats=True)) == []
    assert ALL_MESSAGES_URL not in _requested(client)


def test_the_walk_stops_at_the_first_chat_that_has_been_quiet() -> None:
    quiet = "19:meeting_quiet@thread.v2"
    never = "19:meeting_never@thread.v2"
    routes = _routes(_said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"))
    routes[CHATS_URL] = {
        "value": [
            _chat(),
            _chat(quiet, last_message="2026-01-05T10:00:00Z"),
            _chat(never, last_message=None),
        ]
    }
    client = graph_client(routes)

    items = _walk(connector(client, include_meeting_chats=True))

    # Graph sorts by last message, newest first, and the second chat last spoke
    # before the six months this connector keeps.
    assert len(items) == 1
    assert not [url for url in _requested(client) if quiet in url or never in url]


@pytest.mark.parametrize("walk", ["indexing", "pruning"])
def test_a_chat_listing_that_never_ends_fails_the_attempt(
    monkeypatch: pytest.MonkeyPatch, walk: str
) -> None:
    monkeypatch.setattr(meeting_chats_module, "MAX_CHATS_PER_ORGANIZER", 3)
    other_page = "users/user-1/chats?$skiptoken=p2"
    routes = _routes(_said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"))
    # Two pages that point at each other: neither repeats itself, so only the
    # cap can end the listing.
    routes[CHATS_URL] = {
        **routes[CHATS_URL],
        "@odata.nextLink": f"{SERVICE_ROOT}/{other_page}",
    }
    routes[other_page] = {
        "value": [_chat()],
        "@odata.nextLink": f"{SERVICE_ROOT}/{CHATS_URL}",
    }
    teams_connector = connector(graph_client(routes), include_meeting_chats=True)

    # A walk cut at the cap would read as whole to pruning, which then deletes
    # every chat it did not reach.
    with pytest.raises(RuntimeError, match="did not end"):
        if walk == "indexing":
            _walk(teams_connector)
        else:
            list(teams_connector.retrieve_all_slim_docs())


def test_a_quiet_chat_ends_the_listing_before_its_next_page() -> None:
    next_page = "users/user-1/chats?$skiptoken=p2"
    routes = _routes(_said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"))
    routes[CHATS_URL] = {
        "value": [
            _chat(),
            _chat("19:meeting_quiet@thread.v2", last_message="2026-01-05T10:00:00Z"),
        ],
        "@odata.nextLink": f"{SERVICE_ROOT}/{next_page}",
    }
    client = graph_client(routes)

    items = _walk(connector(client, include_meeting_chats=True))

    # An organizer can hold thousands of old chats behind the first quiet one.
    assert len(items) == 1
    assert next_page not in _requested(client)


def test_a_poll_asks_every_chat_of_the_lookback_what_changed() -> None:
    start = NOW - 3600
    recent = "19:meeting_recent@thread.v2"
    older = "19:meeting_older@thread.v2"
    beyond = "19:meeting_beyond@thread.v2"
    modified = (
        "messages?$top=50&$filter=lastModifiedDateTime gt "
        "2026-09-21T12:33:20Z&$orderby=lastModifiedDateTime desc"
    )
    routes = _routes()
    routes[CHATS_URL] = {
        "value": [
            _chat(recent, last_message="2026-09-20T09:00:00Z"),
            _chat(older, last_message="2026-05-10T09:00:00Z"),
            # Last spoke before the six months this connector keeps.
            _chat(beyond, last_message="2026-01-05T10:00:00Z"),
        ]
    }
    routes[f"chats/{recent}/{modified}"] = {"value": []}
    routes[f"chats/{older}/{modified}"] = {"value": []}
    client = graph_client(routes)

    items = _walk(connector(client, include_meeting_chats=True), start=start)

    # A message deleted in a chat that went quiet months ago must still leave
    # the index, so every chat of the lookback is asked. One request each.
    assert items == []
    assert f"chats/{recent}/{modified}" in _requested(client)
    assert f"chats/{older}/{modified}" in _requested(client)
    assert not [url for url in _requested(client) if beyond in url]


def test_an_edit_to_a_message_older_than_the_lookback_brings_nothing_back() -> None:
    start = NOW - 3600
    modified = (
        f"chats/{CHAT}/messages?$top=50&$filter=lastModifiedDateTime gt "
        "2026-09-21T12:33:20Z&$orderby=lastModifiedDateTime desc"
    )
    routes = _routes()
    routes[CHATS_URL] = {"value": [_chat(last_message="2026-09-21T13:00:00Z")]}
    routes[modified] = {
        "value": [
            _said(
                "m0", "Ancient", "2025-01-05T10:00:00Z", modified="2026-09-21T13:00:00Z"
            )
        ]
    }
    client = graph_client(routes)

    items = _walk(connector(client, include_meeting_chats=True), start=start)

    # Its day is outside what the connector keeps, so no day is read back.
    assert items == []
    assert [url for url in _requested(client) if "createdDateTime lt" in url] == []


def test_a_pasted_image_links_to_the_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    image = f"{SERVICE_ROOT}/chats/{CHAT}/messages/m1/hostedContents/h1/$value"
    said = _said("m1", "See the chart", "2026-09-20T18:59:00Z")
    said["body"]["content"] = f'<p>See the chart</p><img src="{image}">'
    links: list[str | None] = []

    def store(**kwargs: Any) -> tuple[ImageSection, str]:
        links.append(kwargs["link"])
        section = ImageSection(link=kwargs["link"], image_file_id=kwargs["file_id"])
        return section, kwargs["file_id"]

    monkeypatch.setattr(
        images_module, "download_graph_url_with_cap", lambda *_, **__: b"\x89PNG"
    )
    monkeypatch.setattr(images_module, "store_image_and_create_section", store)
    client = graph_client(_routes(said))

    _walk(connector(client, include_meeting_chats=True, include_inline_images=True))

    # Graph gives a chat message no url of its own, so its images cite the chat.
    assert links == [CHAT_URL]


def test_a_poll_rebuilds_the_days_that_changed_with_all_their_messages() -> None:
    start = NOW - 3600
    modified = (
        f"chats/{CHAT}/messages?$top=50&$filter=lastModifiedDateTime gt "
        "2026-09-21T12:33:20Z&$orderby=lastModifiedDateTime desc"
    )
    days_that_changed = (
        f"chats/{CHAT}/messages?$top=50&$filter=createdDateTime lt "
        "2026-09-22T00:00:00Z&$orderby=createdDateTime desc"
    )
    new = _said("m4", "One more thing", "2026-09-21T13:00:00Z")
    earlier_today = _said("m3", "Morning notes", "2026-09-21T08:00:00Z")
    untouched = _said("m2", "Kickoff notes", "2026-09-20T18:59:00Z")
    edited = _said(
        "m1", "Agenda, fixed", "2026-09-18T10:00:00Z", modified="2026-09-21T13:10:00Z"
    )
    before_all = _said("m0", "Invite", "2026-09-17T10:00:00Z")
    routes = _routes()
    routes[CHATS_URL] = {"value": [_chat(last_message="2026-09-21T13:00:00Z")]}
    routes[modified] = {"value": [edited, new]}
    routes[days_that_changed] = {
        "value": [new, earlier_today, untouched, edited, before_all]
    }
    client = graph_client(routes)

    items = _walk(connector(client, include_meeting_chats=True), start=start)

    # A day is a document, so the new message brings back the one written
    # before the window opened. The day between the two that changed is left
    # as it is, and nothing older than the oldest of them is read into a day.
    assert [item.id[-10:] for item in items if isinstance(item, Document)] == [
        "2026-09-21",
        "2026-09-18",
    ]
    today = items[0]
    assert isinstance(today, Document) and len(today.sections) == 2
    assert ALL_MESSAGES_URL not in _requested(client)


def test_a_day_whose_messages_were_all_deleted_replaces_its_document() -> None:
    client = graph_client(
        _routes(
            _said(
                "m1",
                None,
                "2026-09-20T18:59:00Z",
                deleted="2026-09-21T09:00:00Z",
                modified="2026-09-21T09:00:00Z",
            )
        )
    )
    teams_connector = connector(client, include_meeting_chats=True)

    items = _walk(teams_connector)

    # The deleted text would stay searchable until pruning, so the day is
    # written again without it. The slim walk leaves it out, so pruning drops it.
    assert len(items) == 1 and isinstance(items[0], Document)
    assert [section.text for section in items[0].sections] == ["Chat of Launch review"]
    slim = [doc for batch in teams_connector.retrieve_all_slim_docs() for doc in batch]
    assert slim == []


@pytest.mark.parametrize("with_readers", [False, True])
def test_the_slim_walk_lists_the_ids_indexing_writes(with_readers: bool) -> None:
    client = graph_client(
        _routes(
            _said("m2", "Follow up", "2026-09-21T09:00:00Z"),
            _said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"),
        )
    )
    teams_connector = connector(client, include_meeting_chats=True)
    walk = (
        teams_connector.retrieve_all_slim_docs_perm_sync()
        if with_readers
        else teams_connector.retrieve_all_slim_docs()
    )

    slim = [doc for batch in walk for doc in batch if isinstance(doc, SlimDocument)]

    assert [doc.id for doc in slim] == [
        f"teams-chat:user-1:{CHAT}:2026-09-21",
        f"teams-chat:user-1:{CHAT}:2026-09-20",
    ]
    # Pruning needs ids alone, so it lists no members.
    assert (MEMBERS_URL in _requested(client)) is with_readers
    if with_readers:
        assert slim[0].external_access is not None
        assert slim[0].external_access.external_user_emails == {"ada@example.com"}


def test_a_refused_chat_listing_is_one_failure_that_names_the_grant() -> None:
    routes = _routes()
    routes.pop(CHATS_URL)
    client = graph_client(routes, refused={CHATS_URL: PLAIN_403})

    items = _walk(connector(client, include_meeting_chats=True))

    assert len(items) == 1 and isinstance(items[0], ConnectorFailure)
    assert items[0].failed_entity is not None
    assert items[0].failed_entity.entity_id == "user-1"
    assert "Chat.Read.All" in items[0].failure_message


def _two_chats_one_refused(status: int) -> tuple[Any, str]:
    other = "19:meeting_other@thread.v2"
    routes = _routes()
    routes.pop(ALL_MESSAGES_URL)
    routes[CHATS_URL] = {"value": [_chat(), _chat(other, topic="Retro")]}
    routes[f"chats/{other}/members"] = {"value": [_member("ada@example.com", "user-1")]}
    routes[ALL_MESSAGES_URL.replace(CHAT, other)] = {
        "value": [_said("o1", "What went well", "2026-09-19T10:00:00Z")]
    }
    return graph_client(routes, refused={ALL_MESSAGES_URL: status}), other


def test_a_refused_chat_is_left_as_it_is_and_the_next_chat_runs() -> None:
    client, other = _two_chats_one_refused(404)

    items = _walk(connector(client, include_meeting_chats=True))

    # A recorded failure would hold every later poll to this window, for a chat
    # that may never open. The listing answered, so the grant is in place.
    assert not [item for item in items if isinstance(item, ConnectorFailure)]
    assert [item.id for item in items if isinstance(item, Document)] == [
        f"teams-chat:user-1:{other}:2026-09-19"
    ]


def test_the_slim_walk_skips_a_refused_chat_and_goes_on() -> None:
    client, other = _two_chats_one_refused(403)
    teams_connector = connector(client, include_meeting_chats=True)

    slim = [
        d.id
        for batch in teams_connector.retrieve_all_slim_docs()
        for d in batch
        if isinstance(d, SlimDocument)
    ]

    # The refused chat is not listed, so pruning removes its days.
    assert slim == [f"teams-chat:user-1:{other}:2026-09-19"]


@pytest.mark.parametrize(
    ("status", "raised"),
    [(503, GraphRetriesExhausted), (401, requests.HTTPError)],
    ids=["outage", "expired token"],
)
def test_a_chat_error_that_may_pass_fails_the_attempt(
    monkeypatch: pytest.MonkeyPatch, status: int, raised: type[Exception]
) -> None:
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)
    client, _ = _two_chats_one_refused(status)

    # Skipping the chat would lose what changed in it for good.
    with pytest.raises(raised):
        _walk(connector(client, include_meeting_chats=True))


def test_a_refused_organizer_lists_no_chat_and_the_slim_walk_ends_clean() -> None:
    routes = _routes()
    routes.pop(CHATS_URL)
    client = graph_client(routes, refused={CHATS_URL: PLAIN_403})
    teams_connector = connector(client, include_meeting_chats=True)

    # Nothing raises, so the rest of the connector is still pruned and synced.
    assert [
        d for batch in teams_connector.retrieve_all_slim_docs() for d in batch
    ] == []


@pytest.mark.parametrize("listing", ["chats", "messages"])
def test_a_listing_refused_after_it_answered_fails_the_slim_walk(listing: str) -> None:
    next_page = (
        "users/user-1/chats?$skiptoken=p2"
        if listing == "chats"
        else f"chats/{CHAT}/messages?$skiptoken=p2"
    )
    first_page = CHATS_URL if listing == "chats" else ALL_MESSAGES_URL
    routes = _routes(_said("m1", "Kickoff notes", "2026-09-20T18:59:00Z"))
    routes[first_page] = {
        **routes[first_page],
        "@odata.nextLink": f"{SERVICE_ROOT}/{next_page}",
    }
    client = graph_client(routes, refused={next_page: PLAIN_403})
    teams_connector = connector(client, include_meeting_chats=True)

    # What the refused page holds still exists, and a walk that ended clean
    # would have it pruned.
    with pytest.raises(requests.HTTPError):
        list(teams_connector.retrieve_all_slim_docs())


def test_a_chat_refused_after_it_answered_fails_the_index_attempt() -> None:
    next_page = f"chats/{CHAT}/messages?$skiptoken=p2"
    routes = _routes(
        _said("m3", "Follow up", "2026-09-21T09:00:00Z"),
        _said("m2", "Kickoff notes", "2026-09-20T18:59:00Z"),
    )
    routes[ALL_MESSAGES_URL] = {
        **routes[ALL_MESSAGES_URL],
        "@odata.nextLink": f"{SERVICE_ROOT}/{next_page}",
    }
    client = graph_client(routes, refused={next_page: PLAIN_403})

    # The first day is written before the refusal, so ending the chat there
    # would look like a whole poll and skip the rest for good.
    with pytest.raises(requests.HTTPError):
        _walk(connector(client, include_meeting_chats=True))


@pytest.mark.parametrize("refusal", [PLAIN_403, 401])
def test_setup_names_the_chat_grant_when_graph_refuses_the_listing(
    refusal: Refusal,
) -> None:
    routes = _routes()
    routes.pop(CHATS_URL)
    client = graph_client(routes, refused={CHATS_URL: refusal})

    with pytest.raises(InsufficientPermissionsError, match="Chat.Read.All"):
        _validate_organizers(connector(client, include_meeting_chats=True))


def test_setup_passes_on_an_organizer_with_no_meeting_chat() -> None:
    routes = _routes()
    routes[CHATS_URL] = {"value": []}

    _validate_organizers(connector(graph_client(routes), include_meeting_chats=True))
