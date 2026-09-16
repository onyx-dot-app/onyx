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
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

from onyx.configs.app_configs import ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    datetime_from_utc_timestamp,
    time_str_to_utc,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure, EntityFailure
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomRecordingEntry, ZoomSessionOccurrence
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    ZoomSessionType,
    fails_the_whole_run,
)
from onyx.connectors.zoom.recordings.session_types import (
    get_session_type_handler,
    is_portal_upload,
    session_type_for_recording,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_OCCURRENCE_POLL_OVERLAP_SECONDS = ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS * 60 * 60

# pending_work is re-serialized into the checkpoint on every invocation, so
# an uncapped batch makes a years-old meeting rewrite megabytes of JSON.
# Zoom's instances endpoint takes no page parameters, so each page after the
# first re-lists the meeting and slices further in; 200 keeps almost every
# real meeting to a single listing.
_MAX_WORK_PER_STEP = 200

# Zoom's reference puts "The maximum range can be a month" on the `from` parameter
# here, and a wider range comes back clamped rather than refused.
_MAX_LISTING_WINDOW_DAYS = 30

# Past about two years, a poll window this wide is far more likely a connector with
# no indexing start date than a deliberate backfill.
_WIDE_BACKFILL_WINDOWS = 24


def _poll_window_range(
    start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
) -> tuple[datetime, datetime]:
    """A failure covers the lag buffer too, because the buffer is part of the
    window the connector actually asked Zoom for."""
    return (
        datetime.fromtimestamp(
            start - _OCCURRENCE_POLL_OVERLAP_SECONDS, tz=timezone.utc
        ),
        datetime.fromtimestamp(end, tz=timezone.utc),
    )


def _listing_window_range(from_date: date, to_date: date) -> tuple[datetime, datetime]:
    """Zoom scopes a listing by whole UTC days, so a window that failed cost
    exactly those days, not the rest of the poll window."""
    return (
        datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc),
        datetime(to_date.year, to_date.month, to_date.day, tzinfo=timezone.utc)
        + timedelta(days=1),
    )


def _entity_failure(
    entity_id: str,
    message: str,
    missed_time_range: tuple[datetime, datetime],
    error: Exception | None = None,
) -> ConnectorFailure:
    """Discovery moves on, and this range is the only trace the skipped scope
    leaves. Targeted reindex is keyed on document ids, so an entity failure can
    never be replayed: recovery means widening ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS
    or reindexing from scratch.
    """
    return ConnectorFailure(
        failed_entity=EntityFailure(
            entity_id=entity_id,
            missed_time_range=missed_time_range,
        ),
        failure_message=message,
        exception=error,
    )


def _poll_window_dates(
    start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
) -> tuple[date, date]:
    """The lag buffer comes off the start before the dates are rounded, or a
    transcript that lands slowly falls outside the window and is never indexed."""
    from_moment = datetime.fromtimestamp(
        max(start - _OCCURRENCE_POLL_OVERLAP_SECONDS, 0), tz=timezone.utc
    )
    return from_moment.date(), datetime.fromtimestamp(end, tz=timezone.utc).date()


def _listing_windows(from_date: date, to_date: date) -> list[tuple[date, date]]:
    """Zoom never documents whether `to` includes its own date, so windows share
    their boundary day and the last one runs a day past the poll window. Without
    both, a boundary day or the poll window's last day would be asked for by no
    window at all.

    Boundaries fall off from_date alone, so a resumed attempt rebuilds the same list.
    """
    if to_date < from_date:
        return []

    windows: list[tuple[date, date]] = []
    window_start = from_date
    last_date = to_date + timedelta(days=1)
    step = timedelta(days=_MAX_LISTING_WINDOW_DAYS)
    while True:
        window_end = min(window_start + step - timedelta(days=1), last_date)
        windows.append((window_start, window_end))
        if window_end >= last_date:
            return windows
        window_start = window_end


def _occurrence_in_poll_window(
    occurrence: ZoomSessionOccurrence,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
) -> bool:
    """Zoom scopes the listing by whole UTC days, so it still overshoots the
    window at either end and this trims it back to the second. An occurrence
    Zoom sent without a start_time is kept: indexing it twice is cheap, and
    dropping it means the transcript is never indexed at all."""
    if not occurrence.start_time:
        return True
    occurrence_time = time_str_to_utc(occurrence.start_time)
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
    def __init__(
        self, meeting_ids: list[str], webinar_ids: list[str] | None = None
    ) -> None:
        self._refs: list[tuple[ZoomSessionType, str]] = [
            *((ZoomSessionType.MEETING, meeting_id) for meeting_id in meeting_ids),
            *(
                (ZoomSessionType.WEBINAR, webinar_id)
                for webinar_id in webinar_ids or []
            ),
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
        window_start = datetime_from_utc_timestamp(
            int(start - _OCCURRENCE_POLL_OVERLAP_SECONDS)
        )
        window_end = datetime_from_utc_timestamp(int(end))

        failures: list[ConnectorFailure] = []
        occurrences: list[ZoomSessionOccurrence] = []
        try:
            occurrences = handler.list_occurrences(
                client, session_id, window_start, window_end
            )
        except Exception as e:
            if fails_the_whole_run(e):
                raise
            logger.exception(
                "Failed to list Zoom occurrences for session %s", session_id
            )
            failures.append(
                _entity_failure(
                    # 111 is a legal id for both a meeting and a webinar, so
                    # the type has to travel with it or an admin can't tell
                    # which one failed.
                    entity_id=f"{session_type.value}:{session_id}",
                    message=f"Failed to list occurrences for Zoom {session_type.value} {session_id}: {e}",
                    missed_time_range=_poll_window_range(start, end),
                    error=e,
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


class _Host(BaseModel):
    user_id: str
    email: str | None = None

    @property
    def entity_id(self) -> str:
        return f"host:{self.email or self.user_id}"


class _UserRecordingsCursor(BaseModel):
    host_id: str | None = None
    window_start: date | None = None
    after: tuple[str, str] | None = None


def _past_the_poll_window(
    recording: ZoomRecordingEntry, end: SecondsSinceUnixEpoch
) -> bool:
    """Zoom scopes a listing by whole UTC days and the last window asks for one more
    besides, so a session that started after the poll end -- during the attempt, or
    on the day after a resumed attempt's pinned end -- comes back anyway. The next
    poll starts at this end and covers those properly, so indexing them here only
    repeats their transcript downloads against an account-wide rate limit.
    """
    if not recording.start_time:
        return False
    return time_str_to_utc(recording.start_time).timestamp() > end


def _recording_key(recording: ZoomRecordingEntry) -> tuple[str, str]:
    return (recording.start_time or "", recording.uuid)


def _resume_at(hosts: list[_Host], host_id: str | None) -> int:
    """The cursor names the host it stopped on rather than its position, because
    the host list is resolved again on every attempt. A member leaving shifts every
    later position back by one, and the host that slides under the cursor is skipped
    and never indexed.
    """
    if host_id is None:
        return 0
    return bisect_left([host.user_id for host in hosts], host_id)


def _resume_window_at(
    windows: list[tuple[date, date]], window_start: date | None
) -> int:
    """The cursor names the window rather than its index, so a poll window that grew
    at the front cannot shift it."""
    if window_start is None:
        return 0
    return bisect_left([window[0] for window in windows], window_start)


def _advance_host(
    hosts: list["_Host"],
    index: int,
    work: list[OccurrenceWork],
    failures: list[ConnectorFailure],
) -> "DiscoveryStepResult":
    next_index = index + 1
    done = next_index >= len(hosts)
    return DiscoveryStepResult(
        work=work,
        failures=failures,
        next_cursor=None if done else {"host_id": hosts[next_index].user_id},
        done=done,
    )


def _work_from_recording(recording: ZoomRecordingEntry) -> OccurrenceWork | None:
    """Raises rather than skipping a recording it cannot type. A ConnectorFailure
    would end the attempt COMPLETED_WITH_ERRORS, so the next run would rebuild the
    checkpoint over a newer window and never come back for it; raising keeps the
    checkpoint, so widening the sets below is enough to index it on the next run.
    """
    if recording.type is None:
        raise ValueError(f"Zoom recording {recording.uuid} carries no session type")

    session_type = session_type_for_recording(recording.type)
    if session_type is None:
        if is_portal_upload(recording.type):
            logger.info(
                "Skipping Zoom recording %s: uploaded through the web portal rather "
                "than recorded from a session",
                recording.uuid,
            )
            return None
        raise ValueError(
            f"Zoom recording {recording.uuid} has unrecognised session type "
            f"{recording.type!r}"
        )
    return OccurrenceWork(
        session_type=session_type,
        session_id=recording.session_id,
        occurrence_uuid=recording.uuid,
        start_time=recording.start_time,
        topic=recording.topic,
    )


def _list_every_recording(
    client: ZoomClient,
    host: _Host,
    from_date: date,
    to_date: date,
) -> list[ZoomRecordingEntry]:
    """Zoom expires a next_page_token 15 minutes after issuing it, so no token may
    outlive one step. A crawl that resumed holding one would send a dead token, and
    reporting that loses the host's remaining recordings for good: the attempt still
    ends as a success, so the next run moves its poll window on and never returns.
    """
    recordings: list[ZoomRecordingEntry] = []
    page_token: str | None = None
    while True:
        page = client.list_user_recordings(
            user_id=host.user_id,
            from_date=from_date,
            to_date=to_date,
            page_token=page_token,
        )
        recordings.extend(page.recordings)
        page_token = page.next_page_token
        if not page_token:
            return recordings


class _UserRecordingsSource(DiscoverySource):
    """Shared body of the host and Group mechanisms, which differ only in how they
    find their set of hosts.

    `GET /users/{userId}/recordings` declares no age limit, unlike the meeting-ID
    path's 15-month cap, so these two mechanisms are how an admin reaches older
    history. Depth is bounded by the account's own auto-delete policy instead.
    """

    def __init__(self, scope_entity_id: str) -> None:
        self._scope_entity_id = scope_entity_id
        self._resolved: list[_Host] | None = None
        self._listed_key: tuple[str, date] | None = None
        self._listed: list[ZoomRecordingEntry] = []

    @abc.abstractmethod
    def _resolve_hosts(
        self,
        client: ZoomClient,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> tuple[list[_Host], list[ConnectorFailure]]:
        """The hosts to crawl, plus a failure for anything the admin configured
        that resolved to nobody."""
        raise NotImplementedError

    def _hosts(
        self,
        client: ZoomClient,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> tuple[list[_Host], list[ConnectorFailure]]:
        """Resolution costs several API calls, so it runs once per run. Its failures
        come back only on the step that did the work, or every later step would
        report the same failure again.
        """
        if self._resolved is not None:
            return self._resolved, []

        try:
            hosts, failures = self._resolve_hosts(client, start, end)
        except Exception as e:
            if fails_the_whole_run(e):
                raise
            logger.exception(
                "Failed to resolve Zoom hosts for %s", self._scope_entity_id
            )
            hosts = []
            failures = [
                _entity_failure(
                    entity_id=self._scope_entity_id,
                    message=f"Failed to resolve the Zoom hosts for {self._scope_entity_id}: {e}",
                    missed_time_range=_poll_window_range(start, end),
                    error=e,
                )
            ]

        # Zoom promises no order, and `_resume_at` bisects this list, which only
        # works if it is sorted the same way on every attempt.
        hosts.sort(key=lambda host: host.user_id)
        self._resolved = hosts
        return hosts, failures

    def _recordings(
        self,
        client: ZoomClient,
        host: _Host,
        from_date: date,
        to_date: date,
        end: SecondsSinceUnixEpoch,
    ) -> list[ZoomRecordingEntry]:
        """Listing a host again on every step costs another pass over its pages, and
        Zoom's rate limit is account-wide, shared with every other integration the
        customer runs.

        Zoom documents no order here, and a resumed attempt only lines up if the
        order is the same every time.
        """
        key = (host.user_id, from_date)
        if self._listed_key != key:
            # Consecutive windows share their boundary day, so Zoom returns those
            # recordings in both, and indexing them a second time repeats a
            # transcript download. This holds only within an attempt: nothing here
            # is checkpointed, so a resumed attempt lists its first window with no
            # record of the one before it.
            already_listed = (
                {entry.uuid for entry in self._listed}
                if self._listed_key is not None and self._listed_key[0] == host.user_id
                else set()
            )
            recordings = _list_every_recording(client, host, from_date, to_date)
            self._listed = sorted(
                (
                    entry
                    for entry in recordings
                    if entry.uuid not in already_listed
                    and not _past_the_poll_window(entry, end)
                ),
                key=_recording_key,
            )
            self._listed_key = key
        return self._listed

    def _warn_if_backfill_is_wide(
        self, windows: list[tuple[date, date]], hosts: int
    ) -> None:
        """Nothing bounds how long an indexing run may take, and an empty window
        looks like progress rather than a stall, so an unset indexing start date
        stays invisible until Zoom starts refusing calls."""
        if len(windows) <= _WIDE_BACKFILL_WINDOWS:
            return
        logger.warning(
            "Zoom %s is listing recordings from %s, which Zoom's %s-day range cap "
            "splits into %s calls per host (%s hosts, about %s calls). Set an "
            "indexing start date on the connector to narrow this.",
            self._scope_entity_id,
            windows[0][0],
            _MAX_LISTING_WINDOW_DAYS,
            len(windows),
            hosts,
            len(windows) * hosts,
        )

    def discover_step(
        self,
        client: ZoomClient,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        cursor: dict[str, Any] | None,
    ) -> DiscoveryStepResult:
        position = (
            _UserRecordingsCursor.model_validate(cursor)
            if cursor
            else _UserRecordingsCursor()
        )
        hosts, failures = self._hosts(client, start, end)
        index = _resume_at(hosts, position.host_id)
        if index >= len(hosts):
            return DiscoveryStepResult(failures=failures, done=True)

        host = hosts[index]
        # The window and offset belong to the host the cursor named. If that host is
        # gone, `_resume_at` lands on a different one, which starts from the top.
        on_named_host = host.user_id == position.host_id
        windows = _listing_windows(*_poll_window_dates(start, end))
        window_index = (
            _resume_window_at(windows, position.window_start) if on_named_host else 0
        )
        if cursor is None:
            self._warn_if_backfill_is_wide(windows, len(hosts))
        if window_index >= len(windows):
            return _advance_host(hosts, index, [], failures)

        from_date, to_date = windows[window_index]
        resume_after = (
            position.after
            if on_named_host and position.window_start == from_date
            else None
        )

        ordered: list[ZoomRecordingEntry] = []
        try:
            ordered = self._recordings(client, host, from_date, to_date, end)
        except Exception as e:
            if fails_the_whole_run(e):
                raise
            logger.exception(
                "Failed to list Zoom recordings for %s over %s..%s",
                host.entity_id,
                from_date,
                to_date,
            )
            failures.append(
                _entity_failure(
                    entity_id=host.entity_id,
                    message=(
                        f"Failed to list Zoom recordings for {host.entity_id} "
                        f"over {from_date}..{to_date}: {e}"
                    ),
                    missed_time_range=_listing_window_range(from_date, to_date),
                    error=e,
                )
            )

        # Zoom's late transcripts arrive carrying their meeting's own old start time,
        # so entries appear and vanish ahead of where we stopped. A count would move
        # with them; the recording we stopped on does not.
        first = (
            bisect_right([_recording_key(r) for r in ordered], resume_after)
            if resume_after
            else 0
        )

        page = ordered[first : first + _MAX_WORK_PER_STEP]
        work = [
            item
            for item in (_work_from_recording(recording) for recording in page)
            if item is not None
        ]

        if first + len(page) < len(ordered):
            return DiscoveryStepResult(
                work=work,
                failures=failures,
                next_cursor={
                    "host_id": host.user_id,
                    "window_start": windows[window_index][0].isoformat(),
                    "after": _recording_key(page[-1]),
                },
                done=False,
            )

        next_window = window_index + 1
        if next_window < len(windows):
            return DiscoveryStepResult(
                work=work,
                failures=failures,
                next_cursor={
                    "host_id": host.user_id,
                    "window_start": windows[next_window][0].isoformat(),
                },
                done=False,
            )
        return _advance_host(hosts, index, work, failures)


class HostAllowlistSource(_UserRecordingsSource):
    def __init__(self, host_emails: list[str]) -> None:
        super().__init__("host-allowlist")
        self._emails = {email.strip().lower() for email in host_emails if email.strip()}

    def _resolve_hosts(
        self,
        client: ZoomClient,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> tuple[list[_Host], list[ConnectorFailure]]:
        unmatched = set(self._emails)
        hosts: list[_Host] = []
        page_token: str | None = None
        while unmatched:
            page = client.list_users(page_token=page_token)
            for user in page.users:
                email = (user.email or "").strip().lower()
                # Zoom withholds the user id until an invitation is accepted, so
                # leaving that email unmatched reports it below rather than
                # dropping the host in silence.
                if email not in unmatched or not user.id:
                    continue
                unmatched.discard(email)
                hosts.append(_Host(user_id=user.id, email=user.email))

            page_token = page.next_page_token
            if not page_token:
                break

        return hosts, [
            _entity_failure(
                entity_id=f"host:{email}",
                message=f"No active Zoom user has the email {email}, so none of that host's sessions were indexed",
                missed_time_range=_poll_window_range(start, end),
            )
            for email in sorted(unmatched)
        ]


class GroupSource(_UserRecordingsSource):
    def __init__(self, group_id: str) -> None:
        self._group_id = group_id.strip()
        super().__init__(f"group:{self._group_id}")

    def _resolve_hosts(
        self,
        client: ZoomClient,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
    ) -> tuple[list[_Host], list[ConnectorFailure]]:
        """A group id that doesn't exist comes back as a 404, so there is no such
        thing here as a group that resolved to nobody."""
        hosts: list[_Host] = []
        page_token: str | None = None
        while True:
            page = client.list_group_members(self._group_id, page_token=page_token)
            for member in page.users:
                if not member.id:
                    logger.warning(
                        "Skipping Zoom group member %s: no user id until the "
                        "invitation is accepted",
                        member.email,
                    )
                    continue
                hosts.append(_Host(user_id=member.id, email=member.email))

            page_token = page.next_page_token
            if not page_token:
                break

        if not hosts:
            logger.info("Zoom group %s has no members to crawl", self._group_id)
        return hosts, []


def build_discovery_sources(
    meeting_ids: list[str] | None,
    webinar_ids: list[str] | None = None,
    host_emails: list[str] | None = None,
    group_id: str | None = None,
) -> list[DiscoverySource]:
    sources: list[DiscoverySource] = []
    if meeting_ids or webinar_ids:
        sources.append(IdAllowlistSource(meeting_ids or [], webinar_ids or []))
    if host_emails and any(email.strip() for email in host_emails):
        sources.append(HostAllowlistSource(host_emails))
    if group_id and group_id.strip():
        sources.append(GroupSource(group_id))
    return sources
