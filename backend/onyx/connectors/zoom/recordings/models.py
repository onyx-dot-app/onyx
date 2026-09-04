from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

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
