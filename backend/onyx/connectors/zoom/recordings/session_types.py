"""Meetings and webinars need different endpoints to list occurrences and to
read their details, so those calls live behind this handler. Fetching a
transcript does not: one endpoint serves both, and callers use it directly.
"""

import abc

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

# Zoom's `type` code on an entry of the recording listing.
_MEETING_RECORDING_TYPES = frozenset({"1", "2", "3", "4", "7", "8"})
_WEBINAR_RECORDING_TYPES = frozenset({"5", "6", "9"})
_UPLOADED_RECORDING_TYPE = "99"


def session_type_for_recording(
    recording_type: int | str | None,
) -> ZoomSessionType | None:
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


def is_portal_upload(recording_type: int | str | None) -> bool:
    """A file uploaded through Zoom's web Recordings page. Normal to find and normal
    to skip, unlike a code we simply don't recognise."""
    return str(recording_type) == _UPLOADED_RECORDING_TYPE


class SessionTypeHandler(abc.ABC):
    session_type: ZoomSessionType

    @abc.abstractmethod
    def list_occurrences(
        self, client: ZoomClient, session_id: str
    ) -> list[ZoomSessionOccurrence]:
        raise NotImplementedError

    @abc.abstractmethod
    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails:
        raise NotImplementedError

    @abc.abstractmethod
    def fetch_access_list(self, client: ZoomClient, work: OccurrenceWork) -> set[str]:
        """An empty set means no source could name anybody, which the caller
        turns into document-set and group access rather than an empty ACL."""
        raise NotImplementedError


class MeetingSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.MEETING

    def list_occurrences(
        self, client: ZoomClient, session_id: str
    ) -> list[ZoomSessionOccurrence]:
        return client.list_past_meeting_occurrences(session_id)

    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails:
        return client.get_past_meeting_details(occurrence_uuid)

    def fetch_access_list(self, client: ZoomClient, work: OccurrenceWork) -> set[str]:
        """Only participants are per-occurrence. Registrants and invitees hang
        off the scheduled meeting, so on a recurring series they grant access to
        every run, which is accepted: being invited to a series counts as access
        to the series.
        """
        sources: list[AccessSource] = [
            (
                f"the participants of meeting {work.occurrence_uuid}",
                lambda: [
                    p.user_email
                    for p in client.list_past_meeting_participants(work.occurrence_uuid)
                ],
            ),
            (
                f"the registrants of meeting {work.session_id}",
                lambda: approved_registrant_emails(
                    client.list_meeting_registrants(
                        work.session_id, status=APPROVED_REGISTRANT_STATUS
                    )
                ),
            ),
            (
                f"the invitees of meeting {work.session_id}",
                # Zoom returns an external invitee's real address here, unlike
                # the participants endpoint which blanks it. Being invited is what
                # grants access, so don't filter these on internal_user.
                lambda: [
                    i.email for i in client.list_meeting_invitees(work.session_id)
                ],
            ),
        ]
        return union_source_emails(sources)


class WebinarSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.WEBINAR

    def list_occurrences(
        self, client: ZoomClient, session_id: str
    ) -> list[ZoomSessionOccurrence]:
        return client.list_past_webinar_occurrences(session_id)

    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails:
        return client.get_webinar_details(occurrence_uuid)

    def fetch_access_list(self, client: ZoomClient, work: OccurrenceWork) -> set[str]:
        """A webinar has no invitee list to read. Zoom records only who
        registered, who presented and who attended.
        """
        sources: list[AccessSource] = [
            (
                f"the participants of webinar {work.occurrence_uuid}",
                lambda: [
                    p.user_email
                    for p in client.list_past_webinar_participants(work.occurrence_uuid)
                ],
            ),
            (
                f"the registrants of webinar {work.session_id}",
                lambda: approved_registrant_emails(
                    client.list_webinar_registrants(
                        work.session_id, status=APPROVED_REGISTRANT_STATUS
                    )
                ),
            ),
            (
                f"the panelists of webinar {work.session_id}",
                lambda: [
                    p.email for p in client.list_webinar_panelists(work.session_id)
                ],
            ),
        ]
        return union_source_emails(sources)


_HANDLERS: dict[ZoomSessionType, SessionTypeHandler] = {
    ZoomSessionType.MEETING: MeetingSessionType(),
    ZoomSessionType.WEBINAR: WebinarSessionType(),
}


def get_session_type_handler(session_type: ZoomSessionType) -> SessionTypeHandler:
    return _HANDLERS[session_type]
