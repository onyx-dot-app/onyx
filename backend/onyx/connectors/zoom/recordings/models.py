from datetime import datetime, timezone
from enum import Enum
from typing import Any

import requests
from pydantic import BaseModel, Field

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ZoomSessionType(str, Enum):
    MEETING = "meeting"
    WEBINAR = "webinar"


class OccurrenceWork(BaseModel):
    """topic and start_time are optional because some discovery calls already
    return them. A source that has them fills them in, and processing then
    skips the extra per-occurrence details request."""

    session_type: ZoomSessionType
    session_id: str
    occurrence_uuid: str
    start_time: str | None = None
    topic: str | None = None


class RecordingsState(BaseModel):
    source_index: int = 0
    # Only the active source may read what is inside this. The connector
    # stores it and hands it back untouched.
    source_cursor: dict[str, Any] | None = None
    pending_work: list[OccurrenceWork] = Field(default_factory=list)
    work_index: int = 0


def parse_zoom_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        logger.warning("Couldn't parse Zoom timestamp: %s", value)
        return None


# The client's mounted Retry covers 429 but not 408, so a timed-out request
# reaches this unretried.
_RETRY_WORTHY_CLIENT_ERRORS = frozenset({408, 429})


def fails_the_whole_run(error: Exception) -> bool:
    """A ConnectorFailure ends the attempt COMPLETED_WITH_ERRORS, which Onyx
    counts as successful, so the next run rebuilds the checkpoint over a newer
    poll window and never revisits the skipped work. Raising instead fails the
    attempt and keeps the checkpoint, so the next run resumes on the same item.

    Don't wait and retry here. The client already did, honouring Zoom's
    Retry-After, so anything that reaches this has outlived it.
    """
    if isinstance(error, ConnectorValidationError):
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
