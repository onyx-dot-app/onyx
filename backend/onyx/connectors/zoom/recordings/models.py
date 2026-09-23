from enum import Enum
from typing import Any

import requests
from pydantic import BaseModel, Field

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.zoom.models import (
    ZOOM_MEETING_TOO_OLD_CODE,
    ZOOM_NOT_FOUND_CODE,
    ZOOM_USER_NOT_FOUND_CODE,
    ZoomRecordingEntry,
)


class ZoomSessionType(str, Enum):
    MEETING = "meeting"
    WEBINAR = "webinar"


class Host(BaseModel):
    """`user_id` is whatever identifies this person to Zoom: an id a listing
    gave us, or an email an admin typed, which the recordings endpoint also
    accepts."""

    user_id: str
    email: str | None = None

    @property
    def entity_id(self) -> str:
        return f"host:{self.email or self.user_id}"


class OccurrenceWork(BaseModel):
    """topic and start_time are optional because some discovery calls already
    return them. A source that has them fills them in, and processing then
    skips the extra per-occurrence details request."""

    session_type: ZoomSessionType
    session_id: str
    occurrence_uuid: str
    start_time: str | None = None
    topic: str | None = None


class HostScope(BaseModel):
    """The host and Group mechanisms scope by `session_types`, keeping every
    recording of those types. The ID allowlist scopes by `sessions`, keeping
    those numbers whatever else the host recorded."""

    host: Host
    session_types: frozenset[ZoomSessionType] = frozenset()
    sessions: frozenset[tuple[ZoomSessionType, str]] = frozenset()

    def merged_with(self, other: "HostScope") -> "HostScope":
        return HostScope(
            host=Host(
                user_id=self.host.user_id,
                email=self.host.email or other.host.email,
            ),
            session_types=self.session_types | other.session_types,
            sessions=self.sessions | other.sessions,
        )

    def emitted_types(
        self, session_id: str, derived: ZoomSessionType | None
    ) -> set[ZoomSessionType]:
        """Every session type any scope claims for this recording.

        Generous on purpose, because an id the index never held costs nothing
        while a missing one deletes a document. That covers a number configured
        as both a meeting and a webinar, a number typed into the wrong field,
        and a type code Zoom adds after this was written."""
        claimed = {
            session_type
            for session_type, claimed_id in self.sessions
            if claimed_id == session_id
        }
        if derived is None:
            return claimed | set(self.session_types)
        if derived in self.session_types:
            claimed.add(derived)
        return claimed


class SessionHost(BaseModel):
    """What a host-lookup chain found for one configured number.

    `anchor` is the recording Zoom answered with for the number itself, so it
    stands as proof whatever a host listing goes on to say, and it is kept even
    when nobody can be resolved to list."""

    host_id: str | None = None
    anchor: ZoomRecordingEntry | None = None


class RecordingsState(BaseModel):
    source_index: int = 0
    # Only the active source may read what is inside this. The connector
    # stores it and hands it back untouched.
    source_cursor: dict[str, Any] | None = None
    pending_work: list[OccurrenceWork] = Field(default_factory=list)
    work_index: int = 0


# The client's mounted Retry covers 429 but not 408, so a timed-out request
# reaches this unretried.
_RETRY_WORTHY_CLIENT_ERRORS = frozenset({408, 429})


class ZoomListingIncomplete(Exception):
    """Zoom stopped a paged listing early: fewer entries than it counted, a
    cursor that stopped moving, more pages than any account has, or no count
    at all to check the entries against.

    Indexing fails the attempt over this rather than reporting it, because a
    reported failure lets the poll window move on and the entries Zoom left out
    are then never indexed."""


def fails_the_whole_run(error: Exception) -> bool:
    """A ConnectorFailure ends the attempt COMPLETED_WITH_ERRORS, which Onyx
    counts as successful, so the next run rebuilds the checkpoint over a newer
    poll window and never revisits the skipped work. Raising instead fails the
    attempt and keeps the checkpoint, so the next run resumes on the same item.

    Don't wait and retry here. The client already did, honouring Zoom's
    Retry-After, so anything that reaches this has outlived it.
    """
    if isinstance(error, (ConnectorValidationError, ZoomListingIncomplete)):
        return True
    if isinstance(error, requests.HTTPError):
        response = error.response
        return response is not None and (
            response.status_code in _RETRY_WORTHY_CLIENT_ERRORS
            or response.status_code >= 500
        )
    # HTTPError is the only requests error where a response came back to judge.
    # Anything else — dropped connection, exhausted Retry, truncated body — means
    # the exchange broke, which says nothing about this particular session.
    return isinstance(error, requests.RequestException)


def has_no_transcript(error: Exception) -> bool:
    """Zoom answers 404 for a session it never transcribed, which is most of
    them. Reporting that would raise a failure for nearly every session."""
    if not isinstance(error, requests.HTTPError):
        return False
    response = error.response
    return response is not None and response.status_code == 404


def zoom_error_code(error: requests.HTTPError) -> str | None:
    """Zoom puts both "the meeting is too old" and "no such meeting" under a
    400, so the status alone cannot tell them apart."""
    response = error.response
    if response is None:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("code") is None:
        return None
    return str(body["code"])


def definitely_absent(error: Exception) -> bool:
    """Zoom has no such session at all, which is the only answer pruning may
    read as a deletion. Code 12702 is deliberately not in here: it means Zoom
    will not say, not that there is nothing to say."""
    if not isinstance(error, requests.HTTPError) or error.response is None:
        return False
    if error.response.status_code == 404:
        return True
    return (
        error.response.status_code == 400
        and zoom_error_code(error) == ZOOM_NOT_FOUND_CODE
    )


def user_does_not_exist(error: Exception) -> bool:
    """Zoom has no such user, or they belong to another account.

    Checks the code and not only the 404, because the recordings listing also
    answers 404 with code 3301 for a session that was never recorded. Reading
    that as a missing user would delete every document the host ever had."""
    return (
        isinstance(error, requests.HTTPError)
        and error.response is not None
        and error.response.status_code == 404
        and zoom_error_code(error) == ZOOM_USER_NOT_FOUND_CODE
    )


def zoom_cannot_reach_back(error: Exception) -> bool:
    """Code 12702: the session is past the window Zoom will describe. A caller
    may try another call, but may never conclude the session is gone."""
    return (
        isinstance(error, requests.HTTPError)
        and error.response is not None
        and error.response.status_code == 400
        and zoom_error_code(error) == ZOOM_MEETING_TOO_OLD_CODE
    )
