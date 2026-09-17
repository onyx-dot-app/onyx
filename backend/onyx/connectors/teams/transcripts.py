"""Meeting transcripts: Graph exports them per organizer for scheduled meetings
(never channel meetings), behind the OnlineMeetingTranscript.Read.All grant, the
tenant's transcript API access setting and an application access policy that
names the app for the organizer. Each transcript is a document of its own,
readable by the organizer and the people the meeting record lists."""

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
from onyx.connectors.teams.utils import _iter_values, _retry, request_with_retry
from onyx.file_processing.webvtt import is_timing_line, parse_vtt_transcript
from onyx.utils.logger import setup_logger

logger = setup_logger()

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
USER_PAGE_SIZE = 999


def transcript_document_id(transcript_id: str) -> str:
    return f"{TRANSCRIPT_DOCUMENT_ID_PREFIX}{transcript_id}"


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


def graph_error_code(error: requests.HTTPError) -> str:
    """Graph's inner error code, or its outer code, or the empty string."""
    if error.response is None:
        return ""
    try:
        payload = error.response.json()
    except ValueError:
        return ""
    body = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        return ""
    inner = body.get("innerError")
    if isinstance(inner, dict) and inner.get("code"):
        return str(inner["code"])
    return str(body.get("code") or "")


def graph_error_message(error: requests.HTTPError) -> str:
    if error.response is None:
        return ""
    try:
        payload = error.response.json()
    except ValueError:
        return ""
    body = payload.get("error") if isinstance(payload, dict) else None
    return str(body.get("message") or "") if isinstance(body, dict) else ""


def transcripts_disabled(error: requests.HTTPError) -> bool:
    """The tenant setting that turns transcript export off for every app.
    Nothing on our side cures it, so callers stop rather than move on."""
    return graph_error_code(error) == TRANSCRIPT_ACCESS_DISABLED_CODE


def access_policy_missing(error: requests.HTTPError) -> bool:
    """The organizer is outside the application access policy naming this app."""
    return ACCESS_POLICY_MESSAGE in graph_error_message(error).lower()


def fetch_organizers(
    graph_client: GraphClient,
    principal_names: list[str],
    limit: int | None = None,
    before_page: Callable[[], None] | None = None,
) -> list[Organizer]:
    """The configured users, or every enabled user of the tenant when none are
    configured, at most ``limit`` of either. A configured name that resolves to
    nothing raises. ``before_page`` runs ahead of each user page request."""
    select = "$select=id,userPrincipalName,mail,displayName"
    if principal_names:
        # An OData string literal doubles its apostrophes, on top of url encoding.
        return [
            Organizer.from_graph(
                _retry(
                    graph_client,
                    f"users('{quote(name.replace(chr(39), chr(39) * 2), safe='@.')}')"
                    f"?{select}",
                )
            )
            for name in principal_names[:limit]
        ]
    organizers: list[Organizer] = []
    for row in _iter_values(
        graph_client,
        f"users?{select}&$filter=accountEnabled eq true&$top={USER_PAGE_SIZE}",
        before_page,
    ):
        organizers.append(Organizer.from_graph(row))
        if limit is not None and len(organizers) >= limit:
            break
    return organizers


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
        if graph_error_code(e) != SPEAKER_ATTRIBUTION_DISABLED_CODE:
            raise
    return request_with_retry(
        graph_client, request_url, UNATTRIBUTED_FORMAT
    ).text, False


def transcript_text(content: str) -> str:
    """The spoken text. The unattributed format leaves the header out and puts a
    blank line between a cue's timing and its speech, which the WebVTT parser
    reads as two empty blocks, so it falls back to dropping the timing lines."""
    parsed = parse_vtt_transcript(content, keep_speakers=True)
    if parsed:
        return parsed
    lines = [
        stripped
        for line in content.replace("\r\n", "\n").splitlines()
        if (stripped := line.strip())
        and not is_timing_line(stripped)
        and not stripped.startswith("WEBVTT")
    ]
    return "\n\n".join(lines)


def transcript_access(
    organizer: Organizer, meeting: MeetingRecord | None
) -> ExternalAccess:
    """The organizer and everyone the meeting record lists. They were in the
    room, and Graph does not expose an organizer's narrower viewing setting.
    Without the record, the organizer alone."""
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
