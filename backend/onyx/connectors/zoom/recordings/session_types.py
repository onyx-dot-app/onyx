"""Meetings and webinars need different endpoints to list occurrences and to
read their details, so those calls live behind this handler. Fetching a
transcript does not: one endpoint serves both, and callers use it directly.
"""

import abc

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomSessionDetails, ZoomSessionOccurrence
from onyx.connectors.zoom.recordings.models import ZoomSessionType

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
    ) -> ZoomSessionDetails | None:
        raise NotImplementedError


class MeetingSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.MEETING

    def list_occurrences(
        self, client: ZoomClient, session_id: str
    ) -> list[ZoomSessionOccurrence]:
        return client.list_past_meeting_occurrences(session_id)

    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails | None:
        return client.get_past_meeting_details(occurrence_uuid)


class WebinarSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.WEBINAR

    def list_occurrences(
        self, client: ZoomClient, session_id: str
    ) -> list[ZoomSessionOccurrence]:
        return client.list_past_webinar_occurrences(session_id)

    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomSessionDetails | None:
        return client.get_webinar_details(occurrence_uuid)


_HANDLERS: dict[ZoomSessionType, SessionTypeHandler] = {
    ZoomSessionType.MEETING: MeetingSessionType(),
    ZoomSessionType.WEBINAR: WebinarSessionType(),
}


def get_session_type_handler(session_type: ZoomSessionType) -> SessionTypeHandler:
    return _HANDLERS[session_type]
