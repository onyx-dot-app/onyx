"""How an occurrence gets into indexing scope. An admin turns on any mix of an
ID allowlist, a host-email allowlist, and a Zoom Group, and whatever is
configured gets unioned together.

Sources hand back occurrences rather than session IDs because the mechanisms
find them differently: the ID allowlist expands each configured ID, while
host and Group discovery read per-user recording listings that already name
each occurrence. A duplicate arriving from two sources is left alone, since
documents are keyed by occurrence UUID and get upserted.
"""

import abc
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from onyx.configs.app_configs import ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure, EntityFailure
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomMeetingOccurrence
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    ZoomSessionType,
    parse_zoom_datetime,
)
from onyx.connectors.zoom.recordings.session_types import get_session_type_handler
from onyx.utils.logger import setup_logger

logger = setup_logger()

_OCCURRENCE_POLL_OVERLAP_SECONDS = ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS * 60 * 60

# pending_work is re-serialized into the checkpoint on every invocation, so
# an uncapped batch makes a years-old meeting rewrite megabytes of JSON.
# Zoom's instances endpoint takes no date or page parameters, so each page
# after the first re-lists the meeting and slices further in; 200 keeps
# almost every real meeting to a single listing.
_MAX_WORK_PER_STEP = 200


def _occurrence_in_poll_window(
    occurrence: ZoomMeetingOccurrence,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> bool:
    # Keep an occurrence whose start_time won't parse. Indexing it twice is
    # cheap; dropping it means the transcript is never indexed at all.
    occurrence_time = parse_zoom_datetime(occurrence.start_time)
    if occurrence_time is None:
        return True
    return (
        start - _OCCURRENCE_POLL_OVERLAP_SECONDS <= occurrence_time.timestamp() <= end
    )


class DiscoveryStepResult(BaseModel):
    work: list[OccurrenceWork] = Field(default_factory=list)
    failures: list[ConnectorFailure] = Field(default_factory=list)
    next_cursor: dict[str, Any] | None = None
    done: bool = False


class DiscoverySource(abc.ABC):
    @abc.abstractmethod
    def discover_step(
        self,
        client: ZoomClient,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        cursor: dict[str, Any] | None,
    ) -> DiscoveryStepResult:
        """Advance discovery by one bounded unit of work (roughly one API
        call). cursor=None means start from the beginning. Sources convert
        their own errors into failures on the result rather than raising."""
        raise NotImplementedError


class _AllowlistCursor(BaseModel):
    index: int = 0
    offset: int = 0


class IdAllowlistSource(DiscoverySource):
    def __init__(self, meeting_ids: list[str]) -> None:
        self._refs: list[tuple[ZoomSessionType, str]] = [
            (ZoomSessionType.MEETING, meeting_id) for meeting_id in meeting_ids
        ]

    def discover_step(
        self,
        client: ZoomClient,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        cursor: dict[str, Any] | None,
    ) -> DiscoveryStepResult:
        position = (
            _AllowlistCursor.model_validate(cursor) if cursor else _AllowlistCursor()
        )
        if position.index >= len(self._refs):
            return DiscoveryStepResult(done=True)

        session_type, session_id = self._refs[position.index]
        handler = get_session_type_handler(session_type)

        failures: list[ConnectorFailure] = []
        occurrences: list[ZoomMeetingOccurrence] = []
        try:
            occurrences = handler.list_occurrences(client, session_id)
        except Exception as e:
            logger.exception(
                "Failed to list Zoom occurrences for session %s", session_id
            )
            # Record the window this session went uncovered for, the way the
            # Slack and SharePoint connectors do for a channel or site that
            # won't enumerate. Discovery moves on, so without this an admin
            # sees that it failed but not what period is missing.
            failures.append(
                ConnectorFailure(
                    failed_entity=EntityFailure(
                        entity_id=session_id,
                        missed_time_range=(
                            datetime.fromtimestamp(
                                start - _OCCURRENCE_POLL_OVERLAP_SECONDS,
                                tz=timezone.utc,
                            ),
                            datetime.fromtimestamp(end, tz=timezone.utc),
                        ),
                    ),
                    failure_message=f"Failed to list occurrences for Zoom session {session_id}: {e}",
                    exception=e,
                )
            )

        # Zoom promises no order, and paging by offset only lines up if the
        # order is identical every time. Without this, a meeting that runs
        # again mid-backfill shifts entries and one gets stepped past.
        in_window = sorted(
            (o for o in occurrences if _occurrence_in_poll_window(o, start, end)),
            key=lambda o: (o.start_time or "", o.uuid),
        )
        if occurrences and not in_window:
            logger.info(
                "Zoom session %s has no occurrences in the poll window; skipping",
                session_id,
            )

        page = in_window[position.offset : position.offset + _MAX_WORK_PER_STEP]
        work = [
            OccurrenceWork(
                session_type=session_type,
                session_id=session_id,
                occurrence_uuid=occurrence.uuid,
                start_time=occurrence.start_time,
            )
            for occurrence in page
        ]

        next_offset = position.offset + len(page)
        if next_offset < len(in_window):
            return DiscoveryStepResult(
                work=work,
                failures=failures,
                next_cursor={"index": position.index, "offset": next_offset},
                done=False,
            )

        next_index = position.index + 1
        done = next_index >= len(self._refs)
        return DiscoveryStepResult(
            work=work,
            failures=failures,
            next_cursor=None if done else {"index": next_index, "offset": 0},
            done=done,
        )


def build_discovery_sources(meeting_ids: list[str] | None) -> list[DiscoverySource]:
    sources: list[DiscoverySource] = []
    if meeting_ids:
        sources.append(IdAllowlistSource(meeting_ids))
    return sources
