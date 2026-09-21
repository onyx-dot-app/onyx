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
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    SessionHost,
    ZoomSessionType,
    definitely_absent,
    zoom_cannot_reach_back,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Each occurrence costs its own call, and this runs only after every cheaper
# lookup has already said Zoom has no such session.
_MAX_HOST_LOOKUP_OCCURRENCES = 3

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
        lambda: [
            invitee.email
            for invitee in client.get_meeting_details(
                work.session_id
            ).settings.meeting_invitees
        ],
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


HostLookup = tuple[str, Callable[[], str | None]]
HostLookupBuilder = Callable[[ZoomClient, str], HostLookup]


def _host_of_newest_recording(
    client: ZoomClient, occurrences: list[ZoomSessionOccurrence]
) -> str | None:
    """The owner of the newest occurrence that still has a recording. An
    occurrence Zoom has forgotten is skipped, because an older one may still
    answer."""
    newest = sorted(occurrences, key=lambda o: o.start_time or "", reverse=True)[
        :_MAX_HOST_LOOKUP_OCCURRENCES
    ]
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

    @property
    @abc.abstractmethod
    def host_lookups(self) -> tuple[HostLookupBuilder, ...]:
        """Type-specific ways to find a session's host, in the order to try them.
        The recordings lookup is left out because it is the same call for both
        types, so `find_host` makes it first."""
        raise NotImplementedError

    def fetch_access_list(self, client: ZoomClient, work: OccurrenceWork) -> set[str]:
        """Raises ZoomAccessListUnavailable rather than answering with an empty
        set, which would read as nobody having access."""
        return union_source_emails(
            [source(client, work) for source in self.access_sources]
        )

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
            "Zoom has no record of %s %s under any lookup, so its documents will "
            "be pruned",
            self.session_type.value,
            session_id,
        )
        return SessionHost(anchor=anchor)


class MeetingSessionType(SessionTypeHandler):
    session_type = ZoomSessionType.MEETING
    # Only participants are per-occurrence. Registrants and invitees hang off
    # the scheduled meeting, so on a recurring series they grant access to every
    # run, which is accepted: being invited to a series counts as access to the
    # series.
    access_sources = (_meeting_participants, _meeting_registrants, _meeting_invitees)
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
    # A webinar has no invitee list to read. Zoom records only who registered,
    # who presented and who attended.
    access_sources = (_webinar_participants, _webinar_registrants, _webinar_panelists)
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
