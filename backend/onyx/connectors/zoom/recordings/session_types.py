"""Meetings and webinars need different endpoints to list occurrences, to read
their details and to find their host, so those calls live behind this handler.
Fetching a transcript does not: one endpoint serves both, and callers use it
directly.
"""

import abc
from collections.abc import Callable
from datetime import datetime

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomSessionDetails, ZoomSessionOccurrence
from onyx.connectors.zoom.recordings.models import (
    SessionHost,
    ZoomSessionType,
    definitely_absent,
    zoom_cannot_reach_back,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

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
    session type, and the details endpoint is picked from it, so a wrong guess
    cannot be corrected once the document exists.
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


HostLookup = tuple[str, Callable[[], str | None]]
HostLookupBuilder = Callable[[ZoomClient, str], HostLookup]


def _host_of_newest_recording(
    client: ZoomClient, occurrences: list[ZoomSessionOccurrence]
) -> str | None:
    """The owner of the newest occurrence that still has a recording.

    Every run Zoom lists is asked, newest first. Stopping after a few would
    report a series Zoom still lists as one it has no record of, and pruning
    deletes the older runs' documents on that answer. The cost is one call per
    unrecorded run, and only for a series the cheaper lookups could not name."""
    newest = sorted(occurrences, key=lambda o: o.start_time or "", reverse=True)
    for occurrence in newest:
        try:
            return client.get_recording(occurrence.uuid).host_id
        except Exception as e:
            if definitely_absent(e) or zoom_cannot_reach_back(e):
                continue
            raise
    return None


def _meeting_scheduled_host(client: ZoomClient, session_id: str) -> HostLookup:
    return (
        f"the scheduled meeting {session_id}",
        lambda: client.get_meeting_details(session_id).host_id,
    )


def _meeting_past_host(client: ZoomClient, session_id: str) -> HostLookup:
    return (
        f"the past meeting {session_id}",
        lambda: client.get_past_meeting_details(session_id).host_id,
    )


def _meeting_instance_host(client: ZoomClient, session_id: str) -> HostLookup:
    return (
        f"the recent instances of meeting {session_id}",
        lambda: _host_of_newest_recording(
            client, client.list_past_meeting_occurrences(session_id)
        ),
    )


def _webinar_scheduled_host(client: ZoomClient, session_id: str) -> HostLookup:
    return (
        f"the scheduled webinar {session_id}",
        lambda: client.get_webinar_details(session_id).host_id,
    )


def _webinar_instance_host(client: ZoomClient, session_id: str) -> HostLookup:
    return (
        f"the recent instances of webinar {session_id}",
        lambda: _host_of_newest_recording(
            client, client.list_past_webinar_occurrences(session_id)
        ),
    )


class SessionTypeHandler(abc.ABC):
    session_type: ZoomSessionType

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

    @property
    @abc.abstractmethod
    def host_lookups(self) -> tuple[HostLookupBuilder, ...]:
        """Type-specific ways to find a session's host, in the order to try them.
        The recordings lookup is left out because it is the same call for both
        types, so `find_host` makes it first."""
        raise NotImplementedError

    def find_host(self, client: ZoomClient, session_id: str) -> SessionHost:
        """Whose recordings listing can still show this session, plus the
        recording Zoom answered with for the number itself.

        A missing host id only ever means Zoom has no such session, and anything
        short of a clean not-found raises. There is deliberately no third "we
        could not tell" answer, because a caller would write `if unknown:
        continue` and pruning turns that into a deletion."""
        anchor = None
        try:
            anchor = client.get_recording(session_id)
        except Exception as e:
            if not definitely_absent(e):
                raise
        if anchor is not None and anchor.host_id:
            return SessionHost(host_id=anchor.host_id, anchor=anchor)

        for description, fetch in (
            builder(client, session_id) for builder in self.host_lookups
        ):
            try:
                host_id = fetch()
            except Exception as e:
                if zoom_cannot_reach_back(e):
                    logger.info("Zoom will not describe %s any more", description)
                    continue
                if definitely_absent(e):
                    continue
                raise
            if host_id:
                return SessionHost(host_id=host_id, anchor=anchor)

        logger.warning(
            "Zoom has no record of %s %s under any lookup",
            self.session_type.value,
            session_id,
        )
        return SessionHost(anchor=anchor)


class MeetingSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.MEETING
    # The scheduled meeting outlives its recordings, so it is the only lookup
    # that answers for a series whose recent runs were never recorded.
    host_lookups = (_meeting_scheduled_host, _meeting_past_host, _meeting_instance_host)

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
    # No past-webinar details endpoint to match the meeting one.
    host_lookups = (_webinar_scheduled_host, _webinar_instance_host)

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
