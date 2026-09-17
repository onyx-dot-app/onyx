"""Meetings and webinars need different endpoints to list occurrences, to read
their details and to name who had access, so those calls live behind this
handler. Fetching a transcript does not: one endpoint serves both, and callers
use it directly.
"""

import abc
from collections.abc import Callable
from datetime import datetime

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import (
    APPROVED_REGISTRANT_STATUS,
    ZoomSessionDetails,
    ZoomSessionOccurrence,
)
from onyx.connectors.zoom.recordings.access import (
    AccessSource,
    approved_registrant_emails,
    union_source_emails,
)
from onyx.connectors.zoom.recordings.models import OccurrenceWork, ZoomSessionType

# Zoom's `type` code on an entry of the recording listing. The codes and their
# meeting/webinar split come from `meetings[].type` on Cloud Recording > List all
# recordings (GET /users/{userId}/recordings):
# https://developers.zoom.us/docs/api/meetings/#tag/cloud-recording/get/users/%7BuserId%7D/recordings
_MEETING_RECORDING_TYPES = frozenset({"1", "2", "3", "4", "7", "8"})
_WEBINAR_RECORDING_TYPES = frozenset({"5", "6", "9"})
_UPLOADED_RECORDING_TYPE = "99"


def session_type_for_recording(recording_type: int | str) -> ZoomSessionType | None:
    """None means the entry is not a session to index. The code is compared as text
    because Zoom documents it as a string and sends it as an integer.

    Zoom's enum is closed, so a code that matches neither set is a web-portal upload
    or something Zoom added later. Neither is guessed at: a document id freezes the
    session type and ticket 04 picks the access-list endpoint from it, so a wrong
    guess cannot be corrected once the document exists.
    """
    code = str(recording_type)
    if code in _WEBINAR_RECORDING_TYPES:
        return ZoomSessionType.WEBINAR
    if code in _MEETING_RECORDING_TYPES:
        return ZoomSessionType.MEETING
    return None


def is_portal_upload(recording_type: int | str) -> bool:
    """A file uploaded through Zoom's web Recordings page. Normal to find and normal
    to skip, unlike a code we simply don't recognise."""
    return str(recording_type) == _UPLOADED_RECORDING_TYPE


# Builds one source of people who may read a session. A handler lists the sources
# its session type has, and the access list is their union.
AccessSourceBuilder = Callable[[ZoomClient, OccurrenceWork], AccessSource]


def _meeting_participants(client: ZoomClient, work: OccurrenceWork) -> AccessSource:
    return (
        f"the participants of meeting {work.occurrence_uuid}",
        lambda: [
            p.user_email
            for p in client.list_past_meeting_participants(work.occurrence_uuid)
        ],
    )


def _meeting_registrants(client: ZoomClient, work: OccurrenceWork) -> AccessSource:
    return (
        f"the registrants of meeting {work.session_id}",
        lambda: approved_registrant_emails(
            client.list_meeting_registrants(
                work.session_id, status=APPROVED_REGISTRANT_STATUS
            )
        ),
    )


def _meeting_invitees(client: ZoomClient, work: OccurrenceWork) -> AccessSource:
    return (
        f"the invitees of meeting {work.session_id}",
        # Zoom returns an external invitee's real address here, unlike the
        # participants endpoint which blanks it. Being invited is what grants
        # access, so don't filter these on internal_user.
        lambda: [i.email for i in client.list_meeting_invitees(work.session_id)],
    )


def _webinar_participants(client: ZoomClient, work: OccurrenceWork) -> AccessSource:
    return (
        f"the participants of webinar {work.occurrence_uuid}",
        lambda: [
            p.user_email
            for p in client.list_past_webinar_participants(work.occurrence_uuid)
        ],
    )


def _webinar_registrants(client: ZoomClient, work: OccurrenceWork) -> AccessSource:
    return (
        f"the registrants of webinar {work.session_id}",
        lambda: approved_registrant_emails(
            client.list_webinar_registrants(
                work.session_id, status=APPROVED_REGISTRANT_STATUS
            )
        ),
    )


def _webinar_panelists(client: ZoomClient, work: OccurrenceWork) -> AccessSource:
    return (
        f"the panelists of webinar {work.session_id}",
        lambda: [p.email for p in client.list_webinar_panelists(work.session_id)],
    )


class SessionTypeHandler(abc.ABC):
    session_type: ZoomSessionType

    @property
    @abc.abstractmethod
    def access_sources(self) -> tuple[AccessSourceBuilder, ...]:
        """The groups of people Zoom can name for this session type. Abstract so
        a new type that forgets them fails at import, not mid-run."""
        raise NotImplementedError

    @abc.abstractmethod
    def list_occurrences(
        self,
        client: ZoomClient,
        session_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ZoomSessionOccurrence]:
        """The window is a request to Zoom, not a promise: an endpoint that
        can't scope by date ignores it and hands back everything."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails:
        raise NotImplementedError

    def fetch_access_list(self, client: ZoomClient, work: OccurrenceWork) -> set[str]:
        """Raises ZoomAccessListUnavailable rather than answering with an empty
        set, which would read as nobody having access."""
        return union_source_emails(
            [source(client, work) for source in self.access_sources]
        )


class MeetingSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.MEETING
    # Only participants are per-occurrence. Registrants and invitees hang off
    # the scheduled meeting, so on a recurring series they grant access to every
    # run, which is accepted: being invited to a series counts as access to the
    # series.
    access_sources = (_meeting_participants, _meeting_registrants, _meeting_invitees)

    def list_occurrences(
        self,
        client: ZoomClient,
        session_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ZoomSessionOccurrence]:
        return client.list_past_meeting_occurrences(
            session_id, window_start, window_end
        )

    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails:
        return client.get_past_meeting_details(occurrence_uuid)


class WebinarSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.WEBINAR
    # A webinar has no invitee list to read. Zoom records only who registered,
    # who presented and who attended.
    access_sources = (_webinar_participants, _webinar_registrants, _webinar_panelists)

    def list_occurrences(
        self,
        client: ZoomClient,
        session_id: str,
        window_start: datetime,  # noqa: ARG002
        window_end: datetime,  # noqa: ARG002
    ) -> list[ZoomSessionOccurrence]:
        # Zoom's past-webinar instances endpoint takes no date scope.
        return client.list_past_webinar_occurrences(session_id)

    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails:
        return client.get_webinar_details(occurrence_uuid)


_HANDLERS: dict[ZoomSessionType, SessionTypeHandler] = {
    ZoomSessionType.MEETING: MeetingSessionType(),
    ZoomSessionType.WEBINAR: WebinarSessionType(),
}


def get_session_type_handler(session_type: ZoomSessionType) -> SessionTypeHandler:
    return _HANDLERS[session_type]
