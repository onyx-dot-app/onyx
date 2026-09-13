"""Meetings and webinars need different endpoints to list occurrences and to
read their details, so those calls live behind this handler. Fetching a
transcript does not: one endpoint serves both, and callers use it directly.
"""

import abc
from datetime import datetime

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomMeetingOccurrence, ZoomPastMeetingDetails
from onyx.connectors.zoom.recordings.models import ZoomSessionType


class SessionTypeHandler(abc.ABC):
    session_type: ZoomSessionType

    @abc.abstractmethod
    def list_occurrences(
        self,
        client: ZoomClient,
        session_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ZoomMeetingOccurrence]:
        """The window is a request to Zoom, not a promise: an endpoint that
        can't scope by date ignores it and hands back everything."""
        raise NotImplementedError

    @abc.abstractmethod
    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomPastMeetingDetails | None:
        raise NotImplementedError


class MeetingSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.MEETING

    def list_occurrences(
        self,
        client: ZoomClient,
        session_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> list[ZoomMeetingOccurrence]:
        return client.list_past_meeting_occurrences(
            session_id, window_start, window_end
        )

    def get_occurrence_details(
        self, client: ZoomClient, occurrence_uuid: str
    ) -> ZoomPastMeetingDetails | None:
        return client.get_past_meeting_details(occurrence_uuid)


_HANDLERS: dict[ZoomSessionType, SessionTypeHandler] = {
    ZoomSessionType.MEETING: MeetingSessionType(),
}


def get_session_type_handler(session_type: ZoomSessionType) -> SessionTypeHandler:
    return _HANDLERS[session_type]
