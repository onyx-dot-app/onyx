"""Meeting transcripts as documents of their own: who is read, who may read
them, and what each Graph refusal means for the walk and for validation."""

import logging
import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.models import ConnectorFailure, Document, SlimDocument
from onyx.connectors.teams import listing as listing_module
from onyx.connectors.teams import organizers as organizers_module
from onyx.connectors.teams.connector import TeamsCheckpoint, TeamsConnector
from onyx.connectors.teams.organizers import Organizer
from onyx.connectors.teams.transcripts import (
    ATTRIBUTED_FORMAT,
    UNATTRIBUTED_FORMAT,
    fetch_transcripts,
    graph_inner_error_code,
    transcript_document_id,
    transcript_text,
)
from onyx.connectors.teams.utils import GraphRetriesExhausted
from tests.unit.onyx.connectors.teams.helpers import (
    SERVICE_ROOT,
    Refusal,
    connector,
    graph_client,
    step,
)

SELECT_USERS = "$select=id,userPrincipalName,mail,displayName"
# Only an enabled user with a Teams plan can organize a meeting.
ALL_USERS_URL = (
    f"users?{SELECT_USERS}&$filter=accountEnabled eq true and assignedPlans/any("
    "p:p/service eq 'TeamspaceAPI' and p/capabilityStatus eq 'Enabled')"
    "&$count=true&$top=100"
)
ADA = {
    "id": "user-1",
    "userPrincipalName": "Ada@Example.com",
    "mail": "ada@example.com",
    "displayName": "Ada",
}
BOB = {"id": "user-2", "userPrincipalName": "bob@example.com", "mail": None}
START = 1_700_000_000
WINDOW = "startDateTime=2023-11-14T22:13:20Z,endDateTime=2023-11-14T22:13:21Z"
# The clock every test runs at, the end of WINDOW. The setup check lists the 30
# days before it, and nothing is asked of Graph further back than the lookback.
NOW = START + 1
PROBE_WINDOW = "startDateTime=2023-10-15T22:13:21Z"
# Six months before the clock: where a walk with no window of its own starts.
LOOKBACK_WINDOW = "startDateTime=2023-05-15T22:13:21Z"
CONTENT_ROUTE = "users/user-1/onlineMeetings/meeting-1/transcripts/t1/content"
MEETING_URL = (
    "users/user-1/onlineMeetings/meeting-1"
    "?$select=subject,startDateTime,joinWebUrl,participants"
)
JOIN_URL = "https://teams.microsoft.com/l/meetup-join/abc"

SETTING_OFF: Refusal = (403, "GraphAccessToTranscriptsDisabled", "Disabled by admin")
NO_POLICY: Refusal = (
    403,
    "Forbidden",
    "No application access policy found for this app",
)
PLAIN_403: Refusal = (403, "Forbidden", "Forbidden")
# How Graph refuses a transcript's content when the organizer has no policy.
NO_POLICY_ON_CONTENT: Refusal = (
    403,
    "Forbidden",
    "Application is not allowed to perform operations on the user 'user-1', "
    "neither is allowed access through RSC permission evaluation.",
)

ATTRIBUTED_VTT = (
    "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Ada>hello</v>\n\n"
    "00:00:02.000 --> 00:00:03.000\n<v Bob>hi</v>\n"
)
UNATTRIBUTED_TEXT = (
    "00:00:01.500 --> 00:00:04.000 \n\nHello, thanks for joining. \n\n"
    "00:00:04.000 --> 00:00:07.200 \n\nGlad to be here. \n"
)


@pytest.fixture(autouse=True)
def _frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    # The connector and the listing both read time.time, for the probe window
    # and for how far back Graph serves.
    monkeypatch.setattr("time.time", lambda: float(NOW))


def _transcripts_url(organizer_id: str, window: str, top: int = 50) -> str:
    # Every listing carries a start, since no walk reaches past the lookback.
    parameters = f"meetingOrganizerUserId='{organizer_id}',{window}"
    return f"users/{organizer_id}/onlineMeetings/getAllTranscripts({parameters})?$top={top}"


def _transcript(
    transcript_id: str = "t1", meeting_id: str = "meeting-1"
) -> dict[str, Any]:
    return {
        "id": transcript_id,
        "meetingId": meeting_id,
        "createdDateTime": "2024-01-15T10:00:00Z",
        "transcriptContentUrl": (
            f"{SERVICE_ROOT}/users/user-1/onlineMeetings/{meeting_id}"
            f"/transcripts/{transcript_id}/content"
        ),
        "meetingOrganizer": {"user": {"id": "user-1"}},
    }


def _meeting(subject: str | None = "Planning") -> dict[str, Any]:
    return {
        "subject": subject,
        "startDateTime": "2024-01-15T09:00:00Z",
        "joinWebUrl": JOIN_URL,
        "participants": {
            "organizer": {"upn": "Ada@Example.com"},
            "attendees": [{"upn": "Bob@Example.com"}, {"identity": {}}],
        },
    }


def _routes(*transcripts: dict[str, Any], window: str = WINDOW) -> dict[str, Any]:
    return {
        ALL_USERS_URL: {"value": [ADA]},
        _transcripts_url("user-1", window): {"value": list(transcripts)},
        MEETING_URL: _meeting(),
    }


def _walk_transcripts(
    teams_connector: TeamsConnector,
) -> tuple[list[Document | ConnectorFailure], list[bool]]:
    """From a fresh checkpoint with no teams: list teams, list organizers,
    then one batch of organizers per step. Returns the items and has_more per
    step."""
    checkpoint = TeamsCheckpoint(has_more=True)
    items: list[Document | ConnectorFailure] = []
    flags: list[bool] = []
    for _ in range(6):
        page, checkpoint = step(teams_connector, checkpoint, start=START)
        items.extend(page)
        flags.append(checkpoint.has_more)
        if not checkpoint.has_more:
            break
    return items, flags


@pytest.fixture(autouse=True)
def no_teams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(listing_module, "collect_all_teams", lambda **_: [])
    monkeypatch.setattr("onyx.connectors.teams.utils.time.sleep", lambda _: None)


def _validate_organizers(teams_connector: TeamsConnector) -> None:
    assert teams_connector._organizers is not None
    teams_connector._organizers.validate()


def test_transcripts_are_off_by_default() -> None:
    client = graph_client(_routes(_transcript()))

    items, flags = _walk_transcripts(connector(client))

    assert items == [] and flags == [False]
    assert ALL_USERS_URL not in [
        c.args[0] for c in client.execute_request_direct.call_args_list
    ]


def test_a_transcript_becomes_a_document_with_its_meeting_and_readers() -> None:
    client = graph_client(
        _routes(_transcript()),
        contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): ATTRIBUTED_VTT},
    )

    items, flags = _walk_transcripts(
        connector(client, include_meeting_transcripts=True)
    )

    assert flags == [True, True, False]
    assert len(items) == 1
    document = items[0]
    assert isinstance(document, Document)
    assert document.id == transcript_document_id("user-1", "t1")
    assert document.title == "Planning"
    assert document.semantic_identifier == "Planning (2024-01-15)"
    assert [section.text for section in document.sections] == ["Ada: hello\n\nBob: hi"]
    assert document.sections[0].link == JOIN_URL
    assert document.external_access is not None
    assert document.external_access.external_user_emails == {
        "ada@example.com",
        "bob@example.com",
    }
    assert document.external_access.is_public is False
    assert [owner.email for owner in document.primary_owners or []] == [
        "ada@example.com"
    ]
    assert document.metadata["speakers"] == "attributed"
    assert document.metadata["meeting_start"] == "2024-01-15T09:00:00+00:00"
    assert document.doc_updated_at == datetime(2024, 1, 15, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("workers", "steps"),
    [
        # Each step sheds one batch from the checkpoint, so a resumed attempt
        # repeats one batch at most.
        (1, [["teams-transcript:user-2:t2"], ["teams-transcript:user-1:t1"]]),
        # A batch is walked at once, in whatever order its organizers answer.
        (8, [["teams-transcript:user-1:t1", "teams-transcript:user-2:t2"]]),
    ],
)
def test_each_step_indexes_a_batch_of_organizers(
    monkeypatch: pytest.MonkeyPatch, workers: int, steps: list[list[str]]
) -> None:
    monkeypatch.setattr(organizers_module, "ORGANIZER_WORKERS", workers)
    bobs_content = "users/user-2/onlineMeetings/meeting-2/transcripts/t2/content"
    bobs_transcript = {
        "id": "t2",
        "meetingId": "meeting-2",
        "createdDateTime": "2024-01-16T10:00:00Z",
        "transcriptContentUrl": f"{SERVICE_ROOT}/{bobs_content}",
    }
    routes = _routes(_transcript())
    routes[ALL_USERS_URL] = {"value": [ADA, BOB]}
    routes[_transcripts_url("user-2", WINDOW)] = {"value": [bobs_transcript]}
    routes[
        MEETING_URL.replace("user-1", "user-2").replace("meeting-1", "meeting-2")
    ] = _meeting("Retro")
    client = graph_client(
        routes,
        contents={
            (CONTENT_ROUTE, ATTRIBUTED_FORMAT): ATTRIBUTED_VTT,
            (bobs_content, ATTRIBUTED_FORMAT): ATTRIBUTED_VTT,
        },
    )
    teams_connector = connector(client, include_meeting_transcripts=True)

    checkpoint = TeamsCheckpoint(has_more=True)
    per_step: list[list[str]] = []
    while checkpoint.has_more and len(per_step) < 8:
        page, checkpoint = step(teams_connector, checkpoint, start=START)
        per_step.append(sorted(i.id for i in page if isinstance(i, Document)))

    assert [ids for ids in per_step if ids] == steps


def test_the_inner_error_code_wins_and_the_outer_one_is_the_fallback() -> None:
    def refused(body: Any) -> requests.HTTPError:
        answer = MagicMock()
        answer.json.return_value = body
        return requests.HTTPError("403", response=answer)

    inner = {"code": "GraphAccessToTranscriptsDisabled"}
    assert (
        graph_inner_error_code(
            refused({"error": {"code": "Forbidden", "innerError": inner}})
        )
        == "GraphAccessToTranscriptsDisabled"
    )
    assert graph_inner_error_code(refused({"error": {"code": "Forbidden"}})) == (
        "Forbidden"
    )
    assert graph_inner_error_code(refused(["not an object"])) == ""


def test_configured_organizers_are_resolved_by_name() -> None:
    routes = _routes(_transcript())
    routes.pop(ALL_USERS_URL)
    routes[f"users('ada@example.com')?{SELECT_USERS}"] = ADA
    client = graph_client(
        routes, contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): ATTRIBUTED_VTT}
    )

    items, _ = _walk_transcripts(
        connector(
            client,
            include_meeting_transcripts=True,
            meeting_organizers=["ada@example.com"],
        )
    )

    assert [item.id for item in items if isinstance(item, Document)] == [
        transcript_document_id("user-1", "t1")
    ]


def test_a_tenant_without_speaker_attribution_gets_the_plain_transcript() -> None:
    client = graph_client(
        _routes(_transcript()),
        contents={
            (CONTENT_ROUTE, ATTRIBUTED_FORMAT): (
                403,
                "SpeakerAttributionNotAllowed",
                "Retry with the unattributed format",
            ),
            (CONTENT_ROUTE, UNATTRIBUTED_FORMAT): UNATTRIBUTED_TEXT,
        },
    )

    items, _ = _walk_transcripts(connector(client, include_meeting_transcripts=True))

    document = items[0]
    assert isinstance(document, Document)
    assert document.sections[0].text == "Hello, thanks for joining.\n\nGlad to be here."
    assert document.metadata["speakers"] == "unattributed"


def test_a_refused_meeting_record_leaves_the_organizer_alone() -> None:
    routes = _routes(_transcript())
    routes.pop(MEETING_URL)
    client = graph_client(
        routes,
        refused={MEETING_URL: NO_POLICY},
        contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): ATTRIBUTED_VTT},
    )

    items, _ = _walk_transcripts(connector(client, include_meeting_transcripts=True))

    document = items[0]
    assert isinstance(document, Document)
    assert document.title == "Teams meeting on 2024-01-15"
    assert document.sections[0].link is None
    assert document.external_access is not None
    assert document.external_access.external_user_emails == {"ada@example.com"}


def test_a_refused_transcript_is_a_document_failure_and_an_outage_fails_the_attempt() -> (
    None
):
    client = graph_client(
        _routes(_transcript()), contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): 404}
    )

    items, _ = _walk_transcripts(connector(client, include_meeting_transcripts=True))

    assert len(items) == 1 and isinstance(items[0], ConnectorFailure)
    assert items[0].failed_document is not None
    assert items[0].failed_document.document_id == transcript_document_id(
        "user-1", "t1"
    )

    client = graph_client(
        _routes(_transcript()), contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): 503}
    )
    with pytest.raises(GraphRetriesExhausted):
        _walk_transcripts(connector(client, include_meeting_transcripts=True))


def test_a_content_refusal_for_want_of_a_policy_names_the_policy() -> None:
    # Graph words this refusal without the phrase the meeting record uses, so
    # the grants would be blamed for a missing policy.
    client = graph_client(
        _routes(_transcript()),
        contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): NO_POLICY_ON_CONTENT},
    )

    items, _ = _walk_transcripts(connector(client, include_meeting_transcripts=True))

    assert len(items) == 1 and isinstance(items[0], ConnectorFailure)
    assert "application access policy" in items[0].failure_message
    assert "OnlineMeetingTranscript" not in items[0].failure_message


def test_the_tenant_setting_stops_the_walk() -> None:
    routes = _routes()
    routes.pop(_transcripts_url("user-1", WINDOW))
    client = graph_client(
        routes, refused={_transcripts_url("user-1", WINDOW): SETTING_OFF}
    )

    with pytest.raises(ConnectorValidationError, match="turned off"):
        _walk_transcripts(connector(client, include_meeting_transcripts=True))


@pytest.mark.parametrize(
    ("refusal", "named"),
    [
        (NO_POLICY, "application access policy"),
        (PLAIN_403, "OnlineMeetingTranscript"),
        # A user who is gone: no grant to name, so the status and Graph's words.
        (404, "Graph answered 404. Graph said:"),
    ],
)
def test_a_refused_organizer_is_one_recorded_failure(
    refusal: Refusal, named: str
) -> None:
    routes = _routes()
    routes.pop(_transcripts_url("user-1", WINDOW))
    client = graph_client(routes, refused={_transcripts_url("user-1", WINDOW): refusal})

    items, flags = _walk_transcripts(
        connector(client, include_meeting_transcripts=True)
    )

    assert flags[-1] is False
    assert len(items) == 1 and isinstance(items[0], ConnectorFailure)
    assert items[0].failed_entity is not None
    assert items[0].failed_entity.entity_id == "user-1"
    assert named in items[0].failure_message
    # A refusal the connector cannot name still carries Graph's own words.
    if refusal == PLAIN_403:
        assert "Graph said: Forbidden, Forbidden" in items[0].failure_message


def test_documents_flow_before_a_later_listing_page_is_refused() -> None:
    first_page = _transcripts_url("user-1", WINDOW)
    second_page = "users/user-1/onlineMeetings/getAllTranscripts?skipToken=p2"
    routes = _routes()
    routes[first_page] = {
        "value": [_transcript()],
        "@odata.nextLink": f"{SERVICE_ROOT}/{second_page}",
    }
    client = graph_client(
        routes,
        refused={second_page: NO_POLICY},
        contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): ATTRIBUTED_VTT},
    )

    items, _ = _walk_transcripts(connector(client, include_meeting_transcripts=True))

    assert [type(item) for item in items] == [Document, ConnectorFailure]
    failure = items[1]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_entity is not None
    assert failure.failed_entity.entity_id == "user-1"


def test_a_listing_outage_fails_the_attempt() -> None:
    routes = _routes()
    routes.pop(_transcripts_url("user-1", WINDOW))
    client = graph_client(routes, refused={_transcripts_url("user-1", WINDOW): 503})

    with pytest.raises(GraphRetriesExhausted):
        _walk_transcripts(connector(client, include_meeting_transcripts=True))


def test_the_slim_walk_lists_transcripts_with_their_readers() -> None:
    routes = _routes(_transcript(), window=LOOKBACK_WINDOW)
    client = graph_client(routes)

    slim = [
        (
            doc.id,
            doc.external_access.external_user_emails if doc.external_access else None,
        )
        for batch in connector(
            client, include_meeting_transcripts=True
        ).retrieve_all_slim_docs_perm_sync()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    assert slim == [
        (transcript_document_id("user-1", "t1"), {"ada@example.com", "bob@example.com"})
    ]


def test_the_pruning_walk_lists_transcripts_without_reading_their_meetings() -> None:
    routes = {
        ALL_USERS_URL: {"value": [ADA]},
        _transcripts_url("user-1", LOOKBACK_WINDOW): {"value": [_transcript()]},
    }
    client = graph_client(routes)

    slim = [
        (doc.id, doc.external_access)
        for batch in connector(
            client, include_meeting_transcripts=True
        ).retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]

    assert slim == [(transcript_document_id("user-1", "t1"), None)]
    # A meeting read per transcript buys readers the pruning walk discards.
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert MEETING_URL not in requested


def _slim_ids(teams_connector: TeamsConnector) -> list[str]:
    return [
        doc.id
        for batch in teams_connector.retrieve_all_slim_docs_perm_sync()
        for doc in batch
        if isinstance(doc, SlimDocument)
    ]


def test_a_permission_walk_that_leaves_threads_alone_still_lists_transcripts() -> None:
    client = graph_client(_routes(_transcript(), window=LOOKBACK_WINDOW))
    teams_connector = connector(client, include_meeting_transcripts=True)
    teams_connector.skip_threads_in_perm_sync()

    # The sync empties the access of what this walk leaves out, so skipping the
    # channels must not skip the organizers.
    assert _slim_ids(teams_connector) == [transcript_document_id("user-1", "t1")]


def test_a_refused_organizer_lists_nothing_and_the_slim_walk_goes_on() -> None:
    routes: dict[str, Any] = {
        ALL_USERS_URL: {"value": [ADA, BOB]},
        MEETING_URL: _meeting(),
        _transcripts_url("user-2", LOOKBACK_WINDOW): {
            "value": [_transcript("t9", "meeting-9")]
        },
    }
    refused = {_transcripts_url("user-1", LOOKBACK_WINDOW): NO_POLICY}
    client = graph_client(routes, refused=refused)

    slim = _slim_ids(connector(client, include_meeting_transcripts=True))

    # The app lost user-1's transcripts, so none is listed and pruning removes
    # them. The other organizer is still listed.
    assert slim == [transcript_document_id("user-2", "t9")]


def test_a_listing_refused_after_it_answered_fails_the_slim_walk() -> None:
    first_page = _transcripts_url("user-1", LOOKBACK_WINDOW)
    second_page = "users/user-1/onlineMeetings/getAllTranscripts?skipToken=p2"
    routes: dict[str, Any] = {
        ALL_USERS_URL: {"value": [ADA]},
        MEETING_URL: _meeting(),
        first_page: {
            "value": [_transcript()],
            "@odata.nextLink": f"{SERVICE_ROOT}/{second_page}",
        },
    }
    client = graph_client(routes, refused={second_page: NO_POLICY})

    # The transcripts on the refused page still exist, and a walk that ended
    # clean would have them pruned.
    with pytest.raises(requests.HTTPError):
        _slim_ids(connector(client, include_meeting_transcripts=True))


def test_an_organizer_page_that_points_at_itself_fails_the_step() -> None:
    second_users_page = "users?$skiptoken=u2"
    routes = {
        ALL_USERS_URL: {
            "value": [ADA],
            "@odata.nextLink": f"{SERVICE_ROOT}/{second_users_page}",
        },
        second_users_page: {
            "value": [BOB],
            "@odata.nextLink": f"{SERVICE_ROOT}/{second_users_page}",
        },
        _transcripts_url("user-1", WINDOW): {"value": []},
    }
    teams_connector = connector(graph_client(routes), include_meeting_transcripts=True)

    checkpoint = TeamsCheckpoint(has_more=True)
    # The checkpoint saves the link, so a page that points at itself would be
    # indexed again on every step.
    with pytest.raises(RuntimeError, match="repeated a page"):
        for _ in range(8):
            _, checkpoint = step(teams_connector, checkpoint, start=START)


def test_organizers_page_through_the_checkpoint() -> None:
    second_users_page = "users?$skiptoken=u2"
    routes = {
        ALL_USERS_URL: {
            "value": [ADA],
            "@odata.nextLink": f"{SERVICE_ROOT}/{second_users_page}",
        },
        second_users_page: {"value": [BOB]},
        _transcripts_url("user-1", WINDOW): {"value": []},
        _transcripts_url("user-2", WINDOW): {"value": []},
    }
    client = graph_client(routes)
    teams_connector = connector(client, include_meeting_transcripts=True)

    checkpoint = TeamsCheckpoint(has_more=True)
    listed: list[tuple[list[str], str | None]] = []
    flags: list[bool] = []
    while checkpoint.has_more and len(flags) < 8:
        _, checkpoint = step(teams_connector, checkpoint, start=START)
        listed.append(
            (
                [organizer.id for organizer in checkpoint.todo_organizers or []],
                checkpoint.next_organizers_url,
            )
        )
        flags.append(checkpoint.has_more)

    assert listed[1] == (["user-1"], second_users_page)
    assert listed[3] == (["user-2"], None)
    assert flags == [True, True, True, True, False]
    # A saved page is asked for as the advanced query the first one was.
    assert set(client.headers_by_url) == {ALL_USERS_URL, second_users_page}


def test_a_rejected_organizer_page_lists_the_organizers_again() -> None:
    stale_page = "users?$skiptoken=stale"
    client = graph_client(_routes(), refused={stale_page: 400})
    checkpoint = TeamsCheckpoint(
        has_more=True,
        todo_team_ids=[],
        todo_organizers=[],
        next_organizers_url=stale_page,
    )

    _, checkpoint = step(
        connector(client, include_meeting_transcripts=True), checkpoint, start=START
    )

    assert [organizer.id for organizer in checkpoint.todo_organizers or []] == [
        "user-1"
    ]
    assert checkpoint.next_organizers_url is None
    assert checkpoint.has_more is True


def test_a_second_rejected_organizer_page_fails_the_attempt() -> None:
    stale_page = "users?$skiptoken=stale"
    routes = _routes()
    routes[ALL_USERS_URL] = {
        "value": [ADA],
        "@odata.nextLink": f"{SERVICE_ROOT}/{stale_page}",
    }
    client = graph_client(routes, refused={stale_page: 400})
    teams_connector = connector(client, include_meeting_transcripts=True)
    checkpoint = TeamsCheckpoint(
        has_more=True,
        todo_team_ids=[],
        todo_organizers=[],
        next_organizers_url=stale_page,
    )

    # The first rejection lists the organizers again, which hands back the same
    # page url. Restarting on that one too would walk page one for ever.
    _, checkpoint = step(teams_connector, checkpoint, start=START)
    checkpoint.todo_organizers = []
    checkpoint.next_organizers_url = stale_page

    with pytest.raises(requests.HTTPError):
        step(teams_connector, checkpoint, start=START)


def test_an_apostrophe_in_a_configured_organizer_is_doubled_for_odata() -> None:
    routes = {
        f"users('o%27%27neal@example.com')?{SELECT_USERS}": ADA,
        _transcripts_url("user-1", WINDOW): {"value": []},
    }
    client = graph_client(routes)

    _, flags = _walk_transcripts(
        connector(
            client,
            include_meeting_transcripts=True,
            meeting_organizers=["o'neal@example.com"],
        )
    )

    assert flags[-1] is False


def test_a_saved_organizer_is_not_indexed_once_the_option_is_off() -> None:
    client = graph_client(_routes(_transcript()))
    checkpoint = TeamsCheckpoint(
        has_more=True,
        todo_team_ids=[],
        todo_organizers=[Organizer.from_graph(ADA)],
    )

    items, checkpoint = step(connector(client), checkpoint, start=START)

    assert items == [] and checkpoint.has_more is False
    assert _transcripts_url("user-1", WINDOW) not in [
        c.args[0] for c in client.execute_request_direct.call_args_list
    ]


def test_the_slim_walk_honors_a_stop_between_organizers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One organizer per batch, so the order of the checks is not a thread race.
    monkeypatch.setattr(organizers_module, "ORGANIZER_WORKERS", 1)
    routes = {
        ALL_USERS_URL: {"value": [ADA, BOB]},
        _transcripts_url("user-1", LOOKBACK_WINDOW): {"value": [_transcript()]},
        MEETING_URL: _meeting(),
    }
    # User page, first batch, its first page, its one transcript, then the
    # second batch.
    stop_after_first = MagicMock()
    stop_after_first.should_stop.side_effect = [False, False, False, False, True]
    client = graph_client(routes)
    walk = connector(
        client, include_meeting_transcripts=True
    ).retrieve_all_slim_docs_perm_sync(callback=stop_after_first)

    with pytest.raises(RuntimeError, match="Stop signal"):
        list(walk)
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert _transcripts_url("user-1", LOOKBACK_WINDOW) in requested
    assert _transcripts_url("user-2", LOOKBACK_WINDOW) not in requested


def test_the_slim_walk_honors_a_stop_between_transcripts() -> None:
    second_meeting = (
        "users/user-1/onlineMeetings/meeting-2"
        "?$select=subject,startDateTime,joinWebUrl,participants"
    )
    routes = {
        ALL_USERS_URL: {"value": [ADA]},
        _transcripts_url("user-1", LOOKBACK_WINDOW): {
            "value": [_transcript(), _transcript("t2", "meeting-2")]
        },
        MEETING_URL: _meeting(),
        second_meeting: _meeting("Retro"),
    }
    # User page, organizer, first page, first transcript, then the second transcript.
    stop_before_second = MagicMock()
    stop_before_second.should_stop.side_effect = [False, False, False, False, True]
    client = graph_client(routes)
    walk = connector(
        client, include_meeting_transcripts=True
    ).retrieve_all_slim_docs_perm_sync(callback=stop_before_second)

    with pytest.raises(RuntimeError, match="Stop signal"):
        list(walk)
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert MEETING_URL in requested
    assert second_meeting not in requested


def test_the_slim_walk_honors_a_stop_before_the_next_page() -> None:
    first_page = _transcripts_url("user-1", LOOKBACK_WINDOW)
    second_page = "users/user-1/onlineMeetings/getAllTranscripts?skipToken=p2"
    routes = {
        ALL_USERS_URL: {"value": [ADA]},
        first_page: {
            "value": [_transcript()],
            "@odata.nextLink": f"{SERVICE_ROOT}/{second_page}",
        },
        second_page: {"value": [_transcript("t2", "meeting-2")]},
        MEETING_URL: _meeting(),
    }
    # User page, organizer, first page, first transcript, then the second page.
    stop_before_page_two = MagicMock()
    stop_before_page_two.should_stop.side_effect = [False, False, False, False, True]
    client = graph_client(routes)
    walk = connector(
        client, include_meeting_transcripts=True
    ).retrieve_all_slim_docs_perm_sync(callback=stop_before_page_two)

    with pytest.raises(RuntimeError, match="Stop signal"):
        list(walk)
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert first_page in requested
    assert second_page not in requested


def test_the_slim_walk_honors_a_stop_before_the_next_user_page() -> None:
    second_users_page = "users?$skiptoken=u2"
    routes = {
        ALL_USERS_URL: {
            "value": [ADA],
            "@odata.nextLink": f"{SERVICE_ROOT}/{second_users_page}",
        },
        second_users_page: {"value": [BOB]},
        _transcripts_url("user-1", LOOKBACK_WINDOW): {"value": []},
    }
    # A batch of organizers fills from the user listing before any of them is
    # read, so the second check is the page hook ahead of the second user page.
    stop_before_page_two = MagicMock()
    stop_before_page_two.should_stop.side_effect = [False, True]
    client = graph_client(routes)
    walk = connector(
        client, include_meeting_transcripts=True
    ).retrieve_all_slim_docs_perm_sync(callback=stop_before_page_two)

    with pytest.raises(RuntimeError, match="Stop signal"):
        list(walk)
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert ALL_USERS_URL in requested
    assert second_users_page not in requested


def test_plain_transcript_text_drops_timings_and_keeps_speech() -> None:
    assert (
        transcript_text(UNATTRIBUTED_TEXT, attributed=False)
        == "Hello, thanks for joining.\n\nGlad to be here."
    )
    assert transcript_text(ATTRIBUTED_VTT, attributed=True) == "Ada: hello\n\nBob: hi"


def test_plain_speech_shaped_like_a_timing_line_is_kept() -> None:
    content = (
        "00:00:01.000 --> 00:00:02.000\n\n"
        "02:34.567 --> that is when the alert fired\n\n"
        "00:00:02.000 --> 00:00:03.000\n\nWEBVTT is the format\n"
    )

    assert transcript_text(content, attributed=False) == (
        "02:34.567 --> that is when the alert fired\n\nWEBVTT is the format"
    )


def test_a_first_index_starts_at_the_lookback() -> None:
    # The first attempt starts at the epoch. Graph answers 404 on a later page
    # of a window that old, so the listing starts six months before now.
    end = float(START)
    clamped = f"{LOOKBACK_WINDOW},endDateTime=2023-11-14T22:13:20Z"
    client = graph_client({_transcripts_url("user-1", clamped): {"value": []}})

    assert list(fetch_transcripts(client, "user-1", 0, end)) == []


def _two_organizers_whose_listings_meet(window: str) -> MagicMock:
    """A client whose two transcript listings each wait for the other, so a walk
    that takes organizers one at a time breaks the barrier."""
    routes = {
        ALL_USERS_URL: {"value": [ADA, BOB]},
        _transcripts_url("user-1", window): {"value": []},
        _transcripts_url("user-2", window): {"value": []},
    }
    client = graph_client(routes)
    answer = client.execute_request_direct.side_effect
    both_in_flight = threading.Barrier(2, timeout=5)

    def meet(url: str) -> Any:
        if "getAllTranscripts" in url:
            both_in_flight.wait()
        return answer(url)

    client.execute_request_direct.side_effect = meet
    return client


def test_indexing_lists_a_batch_of_organizers_at_the_same_time() -> None:
    client = _two_organizers_whose_listings_meet(WINDOW)

    items, _ = _walk_transcripts(connector(client, include_meeting_transcripts=True))

    assert items == []
    requested = [c.args[0] for c in client.execute_request_direct.call_args_list]
    assert _transcripts_url("user-1", WINDOW) in requested
    assert _transcripts_url("user-2", WINDOW) in requested


def test_the_slim_walk_lists_a_batch_of_organizers_at_the_same_time() -> None:
    client = _two_organizers_whose_listings_meet(LOOKBACK_WINDOW)
    teams_connector = connector(client, include_meeting_transcripts=True)

    assert list(teams_connector.retrieve_all_slim_docs()) == []


def test_every_page_of_licensed_users_is_asked_as_an_advanced_query() -> None:
    # Graph filters on assigned plans only with this header, and a next page
    # asked without it is refused.
    second_page = "users?$skiptoken=u2"
    routes = {
        ALL_USERS_URL: {
            "value": [ADA],
            "@odata.nextLink": f"{SERVICE_ROOT}/{second_page}",
        },
        second_page: {"value": [BOB]},
        _transcripts_url("user-1", LOOKBACK_WINDOW): {"value": []},
        _transcripts_url("user-2", LOOKBACK_WINDOW): {"value": []},
    }
    client = graph_client(routes)
    teams_connector = connector(client, include_meeting_transcripts=True)

    assert list(teams_connector.retrieve_all_slim_docs()) == []
    assert client.headers_by_url == {
        ALL_USERS_URL: {"ConsistencyLevel": "eventual"},
        second_page: {"ConsistencyLevel": "eventual"},
    }


def test_a_window_older_than_graph_serves_asks_for_nothing() -> None:
    client = graph_client({})
    seven_months = 7 * 31 * 24 * 60 * 60

    assert list(fetch_transcripts(client, "user-1", 0, NOW - seven_months)) == []
    assert client.execute_request_direct.call_count == 0


class TestValidation:
    def _connector(
        self,
        routes: dict[str, Any],
        refused: dict[str, Refusal] | None = None,
        contents: dict[tuple[str, str], str | Refusal] | None = None,
        organizers: list[str] | None = None,
    ) -> TeamsConnector:
        return connector(
            graph_client(routes, refused=refused, contents=contents),
            include_meeting_transcripts=True,
            meeting_organizers=organizers,
        )

    def test_an_empty_listing_proves_the_grant_and_passes(self) -> None:
        routes = {
            ALL_USERS_URL: {"value": [ADA]},
            _transcripts_url("user-1", PROBE_WINDOW, 1): {"value": []},
        }

        _validate_organizers(self._connector(routes))

    def test_no_configured_organizers_warns_about_the_policy(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        routes = {
            ALL_USERS_URL: {"value": [ADA]},
            _transcripts_url("user-1", PROBE_WINDOW, 1): {"value": []},
        }

        with caplog.at_level(logging.WARNING):
            _validate_organizers(self._connector(routes))

        assert "every enabled user" in caplog.text

    def test_configured_organizers_pass_without_that_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        routes = {
            f"users('ada@example.com')?{SELECT_USERS}": ADA,
            _transcripts_url("user-1", PROBE_WINDOW, 1): {"value": []},
        }

        with caplog.at_level(logging.WARNING):
            _validate_organizers(
                self._connector(routes, organizers=["ada@example.com"])
            )

        assert "every enabled user" not in caplog.text

    def test_a_transcript_is_read_end_to_end(self) -> None:
        routes = {
            ALL_USERS_URL: {"value": [ADA]},
            _transcripts_url("user-1", PROBE_WINDOW, 1): {"value": [_transcript()]},
            MEETING_URL: _meeting(),
        }

        _validate_organizers(
            self._connector(
                routes, contents={(CONTENT_ROUTE, ATTRIBUTED_FORMAT): ATTRIBUTED_VTT}
            )
        )

    @pytest.mark.parametrize(
        ("refusal", "error", "named"),
        [
            (SETTING_OFF, ConnectorValidationError, "turned off"),
            (NO_POLICY, ConnectorValidationError, "access policy"),
            (PLAIN_403, InsufficientPermissionsError, "OnlineMeetingTranscript"),
            (503, UnexpectedValidationError, "Could not read"),
        ],
    )
    def test_a_refused_listing_names_its_cause(
        self, refusal: Refusal, error: type[Exception], named: str
    ) -> None:
        routes = {ALL_USERS_URL: {"value": [ADA]}}
        refused = {_transcripts_url("user-1", PROBE_WINDOW, 1): refusal}

        with pytest.raises(error, match=named):
            _validate_organizers(self._connector(routes, refused=refused))

    def test_a_refused_meeting_record_names_the_grant(self) -> None:
        routes = {
            ALL_USERS_URL: {"value": [ADA]},
            _transcripts_url("user-1", PROBE_WINDOW, 1): {"value": [_transcript()]},
        }

        with pytest.raises(
            InsufficientPermissionsError, match="OnlineMeetings.Read.All"
        ):
            _validate_organizers(
                self._connector(routes, refused={MEETING_URL: PLAIN_403})
            )

    def test_no_user_to_probe_keeps_the_pair_active(self) -> None:
        with pytest.raises(UnexpectedValidationError, match="No enabled user"):
            _validate_organizers(self._connector({ALL_USERS_URL: {"value": []}}))

    def test_every_configured_organizer_is_resolved(self) -> None:
        routes = {
            f"users('ada@example.com')?{SELECT_USERS}": ADA,
            _transcripts_url("user-1", PROBE_WINDOW, 1): {"value": []},
        }

        with pytest.raises(ConnectorValidationError, match="No user matches"):
            _validate_organizers(
                self._connector(
                    routes, organizers=["ada@example.com", "ghost@example.com"]
                )
            )

    def test_an_unknown_configured_organizer_fails(self) -> None:
        with pytest.raises(ConnectorValidationError, match="No user matches"):
            _validate_organizers(self._connector({}, organizers=["ghost@example.com"]))

    def test_a_refused_user_listing_names_the_grant(self) -> None:
        with pytest.raises(InsufficientPermissionsError, match="User.Read.All"):
            _validate_organizers(
                self._connector({}, refused={ALL_USERS_URL: PLAIN_403})
            )

    def test_a_user_listing_outage_keeps_the_pair_active(self) -> None:
        with pytest.raises(
            UnexpectedValidationError, match="Could not list organizers"
        ):
            _validate_organizers(self._connector({}, refused={ALL_USERS_URL: 503}))
