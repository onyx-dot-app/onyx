"""Meeting transcripts: Graph exports them per organizer for scheduled meetings
(never channel meetings), behind the OnlineMeetingTranscript.Read.All grant, the
tenant's transcript API access setting and an application access policy that
names the app for the organizer. Each transcript is a document of its own,
readable by the organizer and the people the meeting record lists."""

import re
from collections.abc import Callable, Generator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests
from office365.graph_client import GraphClient
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import BasicExpertInfo
from onyx.connectors.teams.utils import (
    _get_next_url,
    _iter_values,
    _retry,
    escape_odata_string,
    request_with_retry,
)
from onyx.file_processing.webvtt import is_timing_line, parse_vtt_transcript

TRANSCRIPT_DOCUMENT_ID_PREFIX = "teams-transcript:"

ATTRIBUTED_FORMAT = "text/vtt"
# The only way to ask for a transcript without speakers: the $format parameter
# does not accept this type.
UNATTRIBUTED_FORMAT = "application/vnd.microsoft.graph.transcript+text"

# Graph's inner error codes. Branch on these, the messages change.
TRANSCRIPT_ACCESS_DISABLED_CODE = "GraphAccessToTranscriptsDisabled"
SPEAKER_ATTRIBUTION_DISABLED_CODE = "SpeakerAttributionNotAllowed"
# A missing application access policy has no code of its own, only this text.
ACCESS_POLICY_MESSAGE = "application access policy"

TRANSCRIPT_PAGE_SIZE = 50
# A page of organizers rides in the indexing checkpoint, so pages stay small.
USER_PAGE_SIZE = 100
ORGANIZERS_URL = (
    "users?$select=id,userPrincipalName,mail,displayName"
    f"&$filter=accountEnabled eq true&$top={USER_PAGE_SIZE}"
)

_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")


def organizer_id_prefix(organizer_id: str) -> str:
    """Every transcript of one organizer starts with this. Their transcripts are
    listed and refused together, so an id says which listing it came from."""
    return f"{TRANSCRIPT_DOCUMENT_ID_PREFIX}{organizer_id}:"


def transcript_document_id(organizer_id: str, transcript_id: str) -> str:
    return f"{organizer_id_prefix(organizer_id)}{transcript_id}"


class Organizer(BaseModel):
    """A user whose scheduled meetings are exported."""

    id: str
    email: str | None
    display_name: str | None

    @classmethod
    def from_graph(cls, row: dict[str, Any]) -> "Organizer":
        return cls(
            id=row["id"],
            email=(row.get("mail") or row.get("userPrincipalName") or None),
            display_name=row.get("displayName"),
        )


class Transcript(BaseModel):
    id: str
    meeting_id: str
    created: datetime
    content_url: str

    @classmethod
    def from_graph(cls, row: dict[str, Any]) -> "Transcript":
        return cls(
            id=row["id"],
            meeting_id=row["meetingId"],
            created=datetime.fromisoformat(row["createdDateTime"]),
            content_url=row["transcriptContentUrl"],
        )


class MeetingRecord(BaseModel):
    """What the meeting itself tells: its name and who was in it."""

    subject: str | None
    start: datetime | None
    join_web_url: str | None
    participant_emails: set[str]

    @classmethod
    def from_graph(cls, row: dict[str, Any]) -> "MeetingRecord":
        participants = row.get("participants") or {}
        people = [
            participants.get("organizer") or {},
            *(participants.get("attendees") or []),
        ]
        emails = {upn.lower() for person in people if (upn := person.get("upn"))}
        start = row.get("startDateTime")
        return cls(
            subject=row.get("subject") or None,
            start=datetime.fromisoformat(start) if start else None,
            join_web_url=row.get("joinWebUrl") or None,
            participant_emails=emails,
        )


def _error_body(error: requests.HTTPError) -> dict[str, Any]:
    """Graph's error object, empty when the body is not one."""
    if error.response is None:
        return {}
    try:
        payload = error.response.json()
    except ValueError:
        return {}
    body = payload.get("error") if isinstance(payload, dict) else None
    return body if isinstance(body, dict) else {}


def graph_inner_error_code(error: requests.HTTPError) -> str:
    """Graph's inner error code, or its outer code, or the empty string. The
    inner one comes first: it names the cause, where the outer one repeats the
    status."""
    body = _error_body(error)
    inner = body.get("innerError")
    if isinstance(inner, dict) and inner.get("code"):
        return str(inner["code"])
    return str(body.get("code") or "")


def graph_error_message(error: requests.HTTPError) -> str:
    return str(_error_body(error).get("message") or "")


def transcripts_disabled(error: requests.HTTPError) -> bool:
    """The tenant setting that turns transcript export off for every app.
    Nothing on our side cures it, so callers stop rather than move on."""
    return graph_inner_error_code(error) == TRANSCRIPT_ACCESS_DISABLED_CODE


def access_policy_missing(error: requests.HTTPError) -> bool:
    """The organizer is outside the application access policy naming this app."""
    return ACCESS_POLICY_MESSAGE in graph_error_message(error).lower()


def iter_organizers(
    graph_client: GraphClient,
    principal_names: list[str],
    before_page: Callable[[], None] | None = None,
) -> Generator[Organizer]:
    """The configured users, or every enabled user of the tenant when none are
    configured. A configured name that resolves to nothing raises.
    ``before_page`` runs ahead of each user page request."""
    if principal_names:
        yield from _resolve_organizers(graph_client, principal_names)
        return
    for row in _iter_values(graph_client, ORGANIZERS_URL, before_page):
        yield Organizer.from_graph(row)


def fetch_organizer_page(
    graph_client: GraphClient, principal_names: list[str], page_url: str | None
) -> tuple[list[Organizer], str | None]:
    """One page of enabled users from ``page_url`` (the first page when None)
    and the link to the next. Configured names are one page of their own."""
    if principal_names:
        return _resolve_organizers(graph_client, principal_names), None
    json_response = _retry(graph_client, page_url or ORGANIZERS_URL)
    organizers = [
        Organizer.from_graph(row)
        for row in json_response.get("value", [])
        if isinstance(row, dict)
    ]
    return organizers, _get_next_url(graph_client, json_response)


def _resolve_organizers(
    graph_client: GraphClient, principal_names: list[str]
) -> list[Organizer]:
    # Eager on purpose: every configured name is resolved even when the caller
    # wants one, so a misspelled name fails at setup and not at index time. A
    # name goes into an OData string literal, so its apostrophes double.
    return [
        Organizer.from_graph(
            _retry(
                graph_client,
                f"users('{quote(escape_odata_string(name), safe='@.')}')"
                "?$select=id,userPrincipalName,mail,displayName",
            )
        )
        for name in principal_names
    ]


def _graph_timestamp(moment: SecondsSinceUnixEpoch) -> str:
    return datetime.fromtimestamp(moment, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def fetch_transcripts(
    graph_client: GraphClient,
    organizer_id: str,
    start: SecondsSinceUnixEpoch | None,
    end: SecondsSinceUnixEpoch | None,
    page_size: int = TRANSCRIPT_PAGE_SIZE,
    before_page: Callable[[], None] | None = None,
) -> Generator[Transcript]:
    """The transcripts of the meetings this user organized, created inside the
    window when one is given. Graph pages the listing itself, ``before_page``
    runs ahead of each page request."""
    parameters = [f"meetingOrganizerUserId='{organizer_id}'"]
    if start is not None:
        parameters.append(f"startDateTime={_graph_timestamp(start)}")
    if end is not None:
        parameters.append(f"endDateTime={_graph_timestamp(end)}")
    url = (
        f"users/{organizer_id}/onlineMeetings/getAllTranscripts"
        f"({','.join(parameters)})?$top={page_size}"
    )
    for row in _iter_values(graph_client, url, before_page):
        yield Transcript.from_graph(row)


def fetch_meeting(
    graph_client: GraphClient, organizer_id: str, meeting_id: str
) -> MeetingRecord:
    """Needs OnlineMeetings.Read.All and the same access policy as the transcripts."""
    return MeetingRecord.from_graph(
        _retry(
            graph_client,
            f"users/{organizer_id}/onlineMeetings/{meeting_id}"
            "?$select=subject,startDateTime,joinWebUrl,participants",
        )
    )


def fetch_transcript_text(
    graph_client: GraphClient, content_url: str
) -> tuple[str, bool]:
    """The transcript as text and whether it names its speakers. A tenant that
    disallows speaker attribution refuses the attributed format and serves the
    plain one, which carries the same speech without the names."""
    request_url = content_url.removeprefix(
        graph_client.service_root_url()
    ).removeprefix("/")
    try:
        return request_with_retry(
            graph_client, request_url, ATTRIBUTED_FORMAT
        ).text, True
    except requests.HTTPError as e:
        if graph_inner_error_code(e) != SPEAKER_ATTRIBUTION_DISABLED_CODE:
            raise
    return request_with_retry(
        graph_client, request_url, UNATTRIBUTED_FORMAT
    ).text, False


def transcript_text(content: str) -> str:
    """The spoken text. The unattributed format puts a blank line between a
    cue's timing and its speech, so the WebVTT parser finds a cue with no text
    and a block with no timing and keeps neither. Then the blocks read in turn."""
    parsed = parse_vtt_transcript(content, keep_speakers=True)
    if parsed:
        return parsed
    return "\n\n".join(_plain_speech(content))


def _plain_speech(content: str) -> list[str]:
    """Blocks alternate between timing and speech. Only a block in timing
    position is read as timing, so speech shaped like a timestamp is kept."""
    blocks = [
        lines
        for block in _BLANK_LINE_RE.split(content.replace("\r\n", "\n"))
        if (lines := [line.strip() for line in block.split("\n") if line.strip()])
    ]
    if blocks and blocks[0][0].startswith("WEBVTT"):
        blocks = blocks[1:]
    speech: list[str] = []
    expect_timing = True
    for lines in blocks:
        if expect_timing and is_timing_line(lines[0]):
            lines = lines[1:]
        speech.extend(lines)
        expect_timing = bool(lines)
    return speech


def transcript_access(
    organizer: Organizer, meeting: MeetingRecord | None
) -> ExternalAccess:
    """The organizer and everyone the meeting record names as organizer or
    attendee: the invited people, since Graph exposes neither who joined nor an
    organizer's narrower viewing setting. Without the record, the organizer."""
    emails = {organizer.email.lower()} if organizer.email else set()
    if meeting is not None:
        emails |= meeting.participant_emails
    return ExternalAccess(
        external_user_emails=emails, external_user_group_ids=set(), is_public=False
    )


def organizer_expert(organizer: Organizer) -> list[BasicExpertInfo]:
    if not organizer.email:
        return []
    return [BasicExpertInfo(display_name=organizer.display_name, email=organizer.email)]
