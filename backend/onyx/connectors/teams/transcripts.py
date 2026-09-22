"""Meeting transcripts: Graph exports them per organizer for scheduled meetings
(never channel meetings), behind the OnlineMeetingTranscript.Read.All grant, the
tenant's transcript API access setting and an application access policy that
names the app for the organizer. Each transcript is a document of its own,
readable by the organizer and the people the meeting record lists."""

import re
import time
from collections.abc import Callable, Generator, Iterator
from datetime import datetime, timezone
from typing import Any

import requests
from office365.graph_client import GraphClient
from pydantic import BaseModel

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    EntityFailure,
    SlimDocument,
    TextSection,
)
from onyx.connectors.teams.organizers import (
    Organizer,
    OrganizerSource,
    organizer_expert,
)
from onyx.connectors.teams.refusals import (
    graph_error_message,
    graph_inner_error_code,
    graph_said,
    is_permanent,
    status,
)
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.sources import PagedListing, SlimWalk
from onyx.connectors.teams.utils import (
    GraphRetriesExhausted,
    get_json_with_retry,
    iter_values,
    request_with_retry,
)
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
# A missing application access policy has no code of its own, only its text:
# the first is how a meeting record is refused, the second a transcript's content.
ACCESS_POLICY_MESSAGES = (
    "application access policy",
    "not allowed to perform operations on the user",
)

TRANSCRIPT_PAGE_SIZE = 50
# Graph walks the listing newest first in slices of about 35 days, about 2
# seconds each with or without transcripts, and answers 404 past the 13th from
# now. Six months keeps a walk short, and every walk shares it so pruning agrees.
TRANSCRIPT_LOOKBACK_S = 183 * 24 * 60 * 60

_BLANK_LINE_RE = re.compile(r"\n[ \t]*\n")


def transcript_document_id(organizer_id: str, transcript_id: str) -> str:
    """Transcripts are listed per organizer, so an id says which listing it
    came from."""
    return f"{TRANSCRIPT_DOCUMENT_ID_PREFIX}{organizer_id}:{transcript_id}"


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


def transcripts_disabled(error: requests.HTTPError) -> bool:
    """The tenant setting that turns transcript export off for every app.
    Nothing on our side cures it, so callers stop rather than move on."""
    return graph_inner_error_code(error) == TRANSCRIPT_ACCESS_DISABLED_CODE


def access_policy_missing(error: requests.HTTPError) -> bool:
    """The organizer is outside the application access policy naming this app."""
    message = graph_error_message(error).lower()
    return any(marker in message for marker in ACCESS_POLICY_MESSAGES)


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
    window when one is given and never further back than the lookback. Graph
    pages the listing itself, ``before_page`` runs ahead of each page request."""
    floor = time.time() - TRANSCRIPT_LOOKBACK_S
    if end is not None and end <= floor:
        return
    parameters = [
        f"meetingOrganizerUserId='{organizer_id}'",
        f"startDateTime={_graph_timestamp(max(start or 0, floor))}",
    ]
    if end is not None:
        parameters.append(f"endDateTime={_graph_timestamp(end)}")
    url = (
        f"users/{organizer_id}/onlineMeetings/getAllTranscripts"
        f"({','.join(parameters)})?$top={page_size}"
    )
    for row in iter_values(graph_client, url, before_page):
        yield Transcript.from_graph(row)


def fetch_meeting(
    graph_client: GraphClient, organizer_id: str, meeting_id: str
) -> MeetingRecord:
    """Needs OnlineMeetings.Read.All and the same access policy as the transcripts."""
    return MeetingRecord.from_graph(
        get_json_with_retry(
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
            graph_client, request_url, {"Accept": ATTRIBUTED_FORMAT}
        ).text, True
    except requests.HTTPError as e:
        if graph_inner_error_code(e) != SPEAKER_ATTRIBUTION_DISABLED_CODE:
            raise
    return request_with_retry(
        graph_client, request_url, {"Accept": UNATTRIBUTED_FORMAT}
    ).text, False


def transcript_text(content: str, attributed: bool) -> str:
    """The spoken text. The attributed format is WebVTT with voice spans. The
    unattributed one puts a blank line between a cue's timing and its speech,
    which the WebVTT parser reads as a cue with no text and a block with no
    timing and keeps neither, so its blocks are read in turn."""
    if attributed:
        return parse_vtt_transcript(content, keep_speakers=True)
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


# A listing costs about 2 seconds for every month it reaches back, and the
# connector form waits 10. A refusal answers the same inside a window, so the
# setup check asks for recent transcripts only.
_TRANSCRIPT_PROBE_WINDOW_S = 30 * 24 * 60 * 60

_TRANSCRIPTS_DISABLED = (
    "Include Meeting Transcripts needs the tenant setting that allows Graph API "
    "access to transcripts, which a Teams administrator has turned off."
)


def _transcript_refusal(error: requests.HTTPError) -> str:
    """The admin-facing cause of a refused transcript call, from Graph's code,
    message or status."""
    if transcripts_disabled(error):
        return _TRANSCRIPTS_DISABLED
    if access_policy_missing(error):
        return (
            "An application access policy naming this app must be granted to the "
            "organizer (or the whole tenant) for meeting transcripts."
        )
    if status(error) == 403:
        return (
            "Include Meeting Transcripts needs the OnlineMeetingTranscript.Read.All "
            f"and OnlineMeetings.Read.All application permissions. {graph_said(error)}"
        )
    return f"Graph answered {status(error)}. {graph_said(error)}"


class TranscriptSource(OrganizerSource):
    option = "Include Meeting Transcripts"

    def __init__(self, session: TeamsSession, covers_every_user: bool) -> None:
        self._session = session
        self._covers_every_user = covers_every_user

    def validate(self, organizer: Organizer) -> None:
        """Lists the organizer's last 30 days and, when there is a transcript,
        reads its meeting and its content: the grants, the tenant setting and the
        access policy all answer on these calls. An empty listing proves the
        listing grant alone, which is enough to run."""
        if self._covers_every_user:
            # The check probes one user, so a policy that covers a group rather
            # than the tenant passes here and refuses users at index time.
            logger.warning(
                "Include Meeting Transcripts has no organizers configured, so it "
                "reads every enabled user with a Teams license. The application "
                "access policy has to cover them all, or list the organizers it "
                "covers."
            )
        graph_client = self._session.graph()
        try:
            probe_start = time.time() - _TRANSCRIPT_PROBE_WINDOW_S
            transcript = next(
                fetch_transcripts(graph_client, organizer.id, probe_start, None, 1),
                None,
            )
            if transcript is None:
                return
            fetch_meeting(graph_client, organizer.id, transcript.meeting_id)
            fetch_transcript_text(graph_client, transcript.content_url)
        except requests.HTTPError as e:
            if transcripts_disabled(e) or access_policy_missing(e):
                raise ConnectorValidationError(_transcript_refusal(e))
            if status(e) in (401, 403):
                raise InsufficientPermissionsError(_transcript_refusal(e))
            raise UnexpectedValidationError(f"Could not read a transcript: {e}")
        except (GraphRetriesExhausted, requests.RequestException) as e:
            raise UnexpectedValidationError(f"Could not read a transcript: {e}")

    def index(
        self,
        organizer: Organizer,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Iterator[Document | ConnectorFailure]:
        """The transcripts one organizer's meetings produced inside the window.
        A refused listing is one recorded failure for the organizer, since the
        access policy is granted per user, except the tenant-wide setting that
        turns transcript export off, which no other organizer escapes."""
        # Documents flow page by page. A document read records its own 403 or
        # 404, so what reaches this handler is a refused listing or an error
        # too general to blame on the organizer.
        try:
            for transcript in fetch_transcripts(
                self._session.graph(), organizer.id, start, end
            ):
                yield self._document(organizer, transcript)
        except requests.HTTPError as e:
            if transcripts_disabled(e):
                raise ConnectorValidationError(_TRANSCRIPTS_DISABLED) from e
            if not is_permanent(e):
                raise
            yield ConnectorFailure(
                failed_entity=EntityFailure(entity_id=organizer.id),
                failure_message=(
                    f"Could not list the meeting transcripts of {organizer.email}: "
                    f"{_transcript_refusal(e)}"
                ),
                exception=e,
            )

    def _meeting_record(
        self, organizer: Organizer, transcript: Transcript
    ) -> MeetingRecord | None:
        """The meeting's name and people. A refused record leaves the transcript
        readable by its organizer alone, anything else fails the attempt."""
        try:
            return fetch_meeting(
                self._session.graph(), organizer.id, transcript.meeting_id
            )
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            logger.warning(
                "Meeting %s of %s is not readable, its transcript is shared with "
                "the organizer alone: %s",
                transcript.meeting_id,
                organizer.email,
                _transcript_refusal(e),
            )
            return None

    def _document(
        self, organizer: Organizer, transcript: Transcript
    ) -> Document | ConnectorFailure:
        meeting = self._meeting_record(organizer, transcript)
        link = meeting.join_web_url if meeting else None
        try:
            content, attributed = fetch_transcript_text(
                self._session.graph(), transcript.content_url
            )
        except requests.HTTPError as e:
            if not is_permanent(e):
                raise
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=transcript_document_id(organizer.id, transcript.id),
                    document_link=link,
                ),
                failure_message=(
                    f"Transcript of meeting {transcript.meeting_id} organized by "
                    f"{organizer.email}: {_transcript_refusal(e)}"
                ),
                exception=e,
            )
        when = (
            meeting.start if meeting and meeting.start else transcript.created
        ).date()
        title = (meeting.subject if meeting else None) or f"Teams meeting on {when}"
        # The slim walk lists every transcript, so an empty one still needs a
        # document or its old text would outlive it.
        text = transcript_text(content, attributed) or title
        return Document(
            id=transcript_document_id(organizer.id, transcript.id),
            sections=[TextSection(link=link, text=text)],
            source=DocumentSource.TEAMS,
            semantic_identifier=f"{title} ({when})",
            title=title,
            doc_created_at=transcript.created,
            doc_updated_at=transcript.created,
            primary_owners=organizer_expert(organizer),
            metadata={
                "organizer": organizer.email or "",
                "meeting_start": (
                    meeting.start.isoformat() if meeting and meeting.start else ""
                ),
                "speakers": "attributed" if attributed else "unattributed",
            },
            external_access=transcript_access(organizer, meeting),
        )

    def slim(self, organizer: Organizer, walk: SlimWalk) -> Iterator[SlimDocument]:
        """One organizer's transcripts. A refused organizer lists nothing and
        the walk goes on: the app lost those transcripts, so pruning removes
        them, and one organizer never costs the rest of the connector its sync."""
        listing = PagedListing(walk)
        try:
            for transcript in fetch_transcripts(
                self._session.graph(),
                organizer.id,
                None,
                None,
                before_page=listing.before_page,
            ):
                walk.raise_if_stopped()
                yield SlimDocument(
                    id=transcript_document_id(organizer.id, transcript.id),
                    external_access=(
                        transcript_access(
                            organizer, self._meeting_record(organizer, transcript)
                        )
                        if walk.with_readers
                        else None
                    ),
                    doc_created_at=transcript.created,
                )
        except requests.HTTPError as e:
            if transcripts_disabled(e):
                raise ConnectorValidationError(_TRANSCRIPTS_DISABLED) from e
            if not listing.lost_access(e):
                raise
            logger.warning(
                "Could not list the transcripts of %s, so their indexed "
                "transcripts are pruned: %s",
                organizer.email,
                _transcript_refusal(e),
            )
