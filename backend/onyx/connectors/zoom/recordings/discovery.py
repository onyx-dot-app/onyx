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
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from onyx.configs.app_configs import ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorFailure, EntityFailure
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomRecordingEntry, ZoomSessionOccurrence
from onyx.connectors.zoom.recordings.models import (
    OccurrenceWork,
    ZoomSessionType,
    fails_the_whole_run,
    parse_zoom_datetime,
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
# Zoom's instances endpoint takes no date or page parameters, so each page
# after the first re-lists the meeting and slices further in; 200 keeps
# almost every real meeting to a single listing.
_MAX_WORK_PER_STEP = 200

# Zoom expires a next_page_token 15 minutes after issuing it, and every occurrence
# on a page is processed before the next page is asked for. Small pages keep that
# gap well inside the token's life.
_RECORDINGS_PAGE_SIZE = 30


def _entity_failure(
    entity_id: str,
    message: str,
    start: SecondsSinceUnixEpoch,
    end: SecondsSinceUnixEpoch,
    error: Exception | None = None,
) -> ConnectorFailure:
    """Discovery moves on, and this window is the only trace the skipped scope
    leaves. Targeted reindex is keyed on document ids, so an entity failure can
    never be replayed: recovery means widening ZOOM_TRANSCRIPT_LAG_BUFFER_HOURS
    or reindexing from scratch.
    """
    return ConnectorFailure(
        failed_entity=EntityFailure(
            entity_id=entity_id,
            missed_time_range=(
                datetime.fromtimestamp(
                    start - _OCCURRENCE_POLL_OVERLAP_SECONDS, tz=timezone.utc
                ),
                datetime.fromtimestamp(end, tz=timezone.utc),
            ),
        ),
        failure_message=message,
        exception=error,
    )


def _poll_window_dates(
    start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
) -> tuple[date, date]:
    """The lag buffer comes off the start before the dates are rounded, or a
    transcript that lands slowly falls outside the window and is never indexed.

    The window is sent whole however long it is, even a first run's epoch-to-now.
    The one-month range cap everyone repeats for this endpoint is not in Zoom's own
    reference, and narrowing it on a guess would silently index a slice of the
    history the admin asked for.
    """
    from_moment = datetime.fromtimestamp(
        max(start - _OCCURRENCE_POLL_OVERLAP_SECONDS, 0), tz=timezone.utc
    )
    return from_moment.date(), datetime.fromtimestamp(end, tz=timezone.utc).date()


def _occurrence_in_poll_window(
    occurrence: ZoomSessionOccurrence,
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
    def __init__(
        self, meeting_ids: list[str], webinar_ids: list[str] | None = None
    ) -> None:
        self._refs: list[tuple[ZoomSessionType, str]] = [
            (ZoomSessionType.MEETING, meeting_id) for meeting_id in meeting_ids
        ]
        self._refs += [
            (ZoomSessionType.WEBINAR, webinar_id) for webinar_id in webinar_ids or []
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
        occurrences: list[ZoomSessionOccurrence] = []
        try:
            occurrences = handler.list_occurrences(client, session_id)
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
                    start=start,
                    end=end,
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
    host_index: int = 0
    page_token: str | None = None
    # Set only while this host is being walked a second time after a page fetch
    # failed. A successful fetch clears it, so it guards against back-to-back
    # failures rather than against a long host being interrupted more than once.
    restarted: bool = False


def _work_from_recording(recording: ZoomRecordingEntry) -> OccurrenceWork | None:
    session_type = session_type_for_recording(recording.type)
    if session_type is None:
        if is_portal_upload(recording.type):
            logger.info(
                "Skipping Zoom recording %s: uploaded through the web portal rather "
                "than recorded from a session",
                recording.uuid,
            )
        else:
            # Loud, because it means Zoom has added a type code and every
            # recording carrying it is going unindexed until someone widens
            # the sets in session_types.py.
            logger.warning(
                "Skipping Zoom recording %s: unrecognised session type %r",
                recording.uuid,
                recording.type,
            )
        return None
    return OccurrenceWork(
        session_type=session_type,
        session_id=recording.session_id,
        occurrence_uuid=recording.uuid,
        start_time=recording.start_time,
        topic=recording.topic,
    )


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
                    start=start,
                    end=end,
                    error=e,
                )
            ]

        # Zoom promises no order. A resumed run resolves again, and the cursor
        # is an index into this list, so a different order would step past a
        # host that was never crawled.
        hosts.sort(key=lambda host: host.user_id)
        self._resolved = hosts
        return hosts, failures

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
        if position.host_index >= len(hosts):
            return DiscoveryStepResult(failures=failures, done=True)

        host = hosts[position.host_index]
        from_date, to_date = _poll_window_dates(start, end)

        work: list[OccurrenceWork] = []
        next_page_token: str | None = None
        try:
            page = client.list_user_recordings(
                user_id=host.user_id,
                from_date=from_date,
                to_date=to_date,
                page_size=_RECORDINGS_PAGE_SIZE,
                page_token=position.page_token,
            )
            work = [
                item
                for item in (
                    _work_from_recording(recording) for recording in page.recordings
                )
                if item is not None
            ]
            next_page_token = page.next_page_token
        except Exception as e:
            if fails_the_whole_run(e):
                raise
            # Zoom expires a page token 15 minutes after issuing it, so a crawl
            # that resumes later sends a dead one. Reporting that would abandon
            # everything after this page: the attempt still ends as a success,
            # so the next run moves its poll window on and never comes back.
            # Walking the host again from its first page costs duplicates the
            # upsert absorbs, and is only tried once in a row.
            if position.page_token and not position.restarted:
                logger.warning(
                    "Restarting Zoom recordings for %s from the first page: %s",
                    host.entity_id,
                    e,
                )
                return DiscoveryStepResult(
                    failures=failures,
                    next_cursor={
                        "host_index": position.host_index,
                        "restarted": True,
                    },
                    done=False,
                )

            logger.exception("Failed to list Zoom recordings for %s", host.entity_id)
            failures.append(
                _entity_failure(
                    entity_id=host.entity_id,
                    message=f"Failed to list Zoom recordings for {host.entity_id}: {e}",
                    start=start,
                    end=end,
                    error=e,
                )
            )

        if next_page_token:
            return DiscoveryStepResult(
                work=work,
                failures=failures,
                next_cursor={
                    "host_index": position.host_index,
                    "page_token": next_page_token,
                },
                done=False,
            )

        next_index = position.host_index + 1
        done = next_index >= len(hosts)
        return DiscoveryStepResult(
            work=work,
            failures=failures,
            next_cursor=None if done else {"host_index": next_index},
            done=done,
        )


class HostAllowlistSource(_UserRecordingsSource):
    def __init__(self, host_emails: list[str]) -> None:
        super().__init__("host-allowlist")
        self._emails = sorted(
            {email.strip().lower() for email in host_emails if email.strip()}
        )

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
                start=start,
                end=end,
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
