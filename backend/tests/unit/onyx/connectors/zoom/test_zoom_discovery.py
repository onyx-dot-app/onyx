import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import (
    ZoomRecordingEntry,
    ZoomRecordingPage,
    ZoomSessionOccurrence,
    ZoomUser,
    ZoomUserPage,
)
from onyx.connectors.zoom.recordings.discovery import (
    _MAX_WORK_PER_STEP,
    _OCCURRENCE_POLL_OVERLAP_SECONDS,
    _RECORDINGS_PAGE_SIZE,
    GroupSource,
    HostAllowlistSource,
    IdAllowlistSource,
    build_discovery_sources,
)
from onyx.connectors.zoom.recordings.models import ZoomSessionType

# Fixed rather than time.time(): a float from the clock can carry more
# precision than datetime keeps, so round-tripping it through a datetime
# doesn't always compare equal.
_START = 0.0
_END = 2_000_000_000.0
_ONE_HOUR = 60 * 60


def _occurrence_at(uuid: str, epoch_seconds: float) -> ZoomSessionOccurrence:
    return ZoomSessionOccurrence(
        uuid=uuid,
        start_time=datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat(),
    )


def _client_with_occurrences(
    occurrences: list[ZoomSessionOccurrence],
) -> MagicMock:
    client = MagicMock(spec=ZoomClient)
    client.list_past_meeting_occurrences.return_value = occurrences
    return client


class TestIdAllowlistSource:
    def test_one_id_expanded_per_step_with_cursor_progression(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_meeting_occurrences.side_effect = lambda session_id: [
            ZoomSessionOccurrence(uuid=f"uuid-{session_id}")
        ]

        first = source.discover_step(client, _START, _END, None)
        assert [w.occurrence_uuid for w in first.work] == ["uuid-111"]
        assert first.done is False
        assert first.next_cursor == {"index": 1, "offset": 0}

        second = source.discover_step(client, _START, _END, first.next_cursor)
        assert [w.occurrence_uuid for w in second.work] == ["uuid-222"]
        assert second.done is True
        assert second.next_cursor is None

    def test_work_items_carry_session_identity(self) -> None:
        source = IdAllowlistSource(["111"])
        client = _client_with_occurrences(
            [ZoomSessionOccurrence(uuid="uuid-1", start_time="2026-01-15T10:00:00Z")]
        )

        result = source.discover_step(client, _START, _END, None)

        work = result.work[0]
        assert work.session_type == ZoomSessionType.MEETING
        assert work.session_id == "111"
        assert work.occurrence_uuid == "uuid-1"
        assert work.start_time == "2026-01-15T10:00:00Z"

    def test_recurring_id_yields_one_work_item_per_occurrence(self) -> None:
        source = IdAllowlistSource(["111"])
        client = _client_with_occurrences(
            [
                ZoomSessionOccurrence(uuid="uuid-1", start_time="2026-01-01T10:00:00Z"),
                ZoomSessionOccurrence(uuid="uuid-2", start_time="2026-01-08T10:00:00Z"),
                ZoomSessionOccurrence(uuid="uuid-3", start_time="2026-01-15T10:00:00Z"),
            ]
        )

        result = source.discover_step(client, _START, _END, None)

        assert [w.occurrence_uuid for w in result.work] == [
            "uuid-1",
            "uuid-2",
            "uuid-3",
        ]
        assert result.done is True

    def test_listing_failure_reports_entity_failure_and_still_advances(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_meeting_occurrences.side_effect = RuntimeError("boom")

        result = source.discover_step(client, _START, _END, None)

        assert result.work == []
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.failed_entity is not None
        assert failure.failed_entity.entity_id == "meeting:111"
        # Discovery moves on, so the failure has to say which window went
        # uncovered or the gap is invisible to an admin.
        missed = failure.failed_entity.missed_time_range
        assert missed is not None
        missed_start, missed_end = missed
        assert missed_end.timestamp() == _END
        assert missed_start.timestamp() == _START - _OCCURRENCE_POLL_OVERLAP_SECONDS
        assert failure.exception is not None
        assert result.next_cursor == {"index": 1, "offset": 0}
        assert result.done is False

    def test_cursor_past_end_is_done(self) -> None:
        source = IdAllowlistSource(["111"])
        client = MagicMock(spec=ZoomClient)

        result = source.discover_step(client, _START, _END, {"index": 5})

        assert result.work == []
        assert result.done is True
        client.list_past_meeting_occurrences.assert_not_called()


class TestIdAllowlistPollWindow:
    def test_steady_state_poll_only_keeps_occurrences_in_window(self) -> None:
        source = IdAllowlistSource(["111"])
        now = time.time()
        client = _client_with_occurrences(
            [
                _occurrence_at("uuid-old", now - 30 * 24 * 60 * 60),
                _occurrence_at("uuid-new", now - 60),
            ]
        )

        # Poll as a steady-state run would: start at the last successful run.
        result = source.discover_step(client, now - _ONE_HOUR, now, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-new"]

    def test_overlap_buffer_keeps_occurrence_just_before_window_start(self) -> None:
        source = IdAllowlistSource(["111"])
        now = time.time()
        poll_start = now - _ONE_HOUR
        inside_buffer = poll_start - (_OCCURRENCE_POLL_OVERLAP_SECONDS - _ONE_HOUR)
        client = _client_with_occurrences(
            [_occurrence_at("uuid-recovering", inside_buffer)]
        )

        result = source.discover_step(client, poll_start, now, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-recovering"]

    def test_occurrence_older_than_overlap_buffer_is_excluded(self) -> None:
        source = IdAllowlistSource(["111"])
        now = time.time()
        poll_start = now - _ONE_HOUR
        outside_buffer = poll_start - (_OCCURRENCE_POLL_OVERLAP_SECONDS + _ONE_HOUR)
        client = _client_with_occurrences(
            [_occurrence_at("uuid-too-old", outside_buffer)]
        )

        result = source.discover_step(client, poll_start, now, None)

        assert result.work == []
        # Nothing to do for this id, so it has to move on rather than stall.
        assert result.done is True

    def test_occurrence_after_the_window_end_is_excluded(self) -> None:
        source = IdAllowlistSource(["111"])
        now = time.time()
        client = _client_with_occurrences(
            [_occurrence_at("uuid-future", now + 30 * 24 * _ONE_HOUR)]
        )

        result = source.discover_step(client, now - _ONE_HOUR, now, None)

        # The window is bounded at both ends; a future date (clock skew, or a
        # scheduled instance) is not this poll's business.
        assert result.work == []

    def test_unparseable_start_time_is_kept_rather_than_dropped(self) -> None:
        source = IdAllowlistSource(["111"])
        now = time.time()
        client = _client_with_occurrences(
            [ZoomSessionOccurrence(uuid="uuid-junk", start_time="not-a-date")]
        )

        # A narrow window that a real date would fall outside of: the point is
        # that a timestamp we can't read must not cost us the transcript.
        result = source.discover_step(client, now - 60, now, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-junk"]

    def test_occurrence_without_start_time_is_never_filtered_out(self) -> None:
        source = IdAllowlistSource(["111"])
        now = time.time()
        client = _client_with_occurrences(
            [ZoomSessionOccurrence(uuid="uuid-no-time", start_time=None)]
        )

        # A window so narrow any dated occurrence would fall outside it.
        result = source.discover_step(client, now - 60, now, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-no-time"]


class TestIdAllowlistPaging:
    def test_long_running_meeting_is_paged_across_steps(self) -> None:
        total = _MAX_WORK_PER_STEP * 2 + 20
        source = IdAllowlistSource(["111"])
        client = _client_with_occurrences(
            [
                ZoomSessionOccurrence(
                    uuid=f"uuid-{i:04d}",
                    start_time=f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00Z",
                )
                for i in range(total)
            ]
        )

        seen: list[str] = []
        cursor: dict | None = None
        steps = 0
        while True:
            steps += 1
            result = source.discover_step(client, _START, _END, cursor)
            assert len(result.work) <= _MAX_WORK_PER_STEP
            seen.extend(w.occurrence_uuid for w in result.work)
            cursor = result.next_cursor
            if result.done:
                break
            assert steps < 10

        assert steps == 3
        assert seen == [f"uuid-{i:04d}" for i in range(total)]

    def test_exact_multiple_of_the_cap_needs_no_extra_empty_step(self) -> None:
        source = IdAllowlistSource(["111"])
        client = _client_with_occurrences(
            [
                ZoomSessionOccurrence(
                    uuid=f"uuid-{i:04d}",
                    start_time=f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
                )
                for i in range(_MAX_WORK_PER_STEP)
            ]
        )

        result = source.discover_step(client, _START, _END, None)

        # next_offset == len here, so the "is there more" check must not send
        # us round again for an empty page.
        assert len(result.work) == _MAX_WORK_PER_STEP
        assert result.done is True
        assert result.next_cursor is None

    def test_unrecognised_cursor_restarts_the_id_instead_of_raising(self) -> None:
        source = IdAllowlistSource(["111"])
        client = _client_with_occurrences(
            [ZoomSessionOccurrence(uuid="uuid-1", start_time="2026-01-15T10:00:00Z")]
        )

        # A checkpoint we can't make sense of should re-do work, never skip it.
        result = source.discover_step(client, _START, _END, {"bogus": "value"})

        assert [w.occurrence_uuid for w in result.work] == ["uuid-1"]

    def test_paging_cursor_carries_index_and_offset(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = _client_with_occurrences(
            [
                ZoomSessionOccurrence(
                    uuid=f"uuid-{i:04d}", start_time=f"2026-01-01T00:{i:02d}:00Z"
                )
                for i in range(_MAX_WORK_PER_STEP + 1)
            ]
        )

        first = source.discover_step(client, _START, _END, None)
        assert first.next_cursor == {"index": 0, "offset": _MAX_WORK_PER_STEP}
        assert first.done is False

        second = source.discover_step(client, _START, _END, first.next_cursor)
        assert second.next_cursor == {"index": 1, "offset": 0}

    def test_new_occurrence_mid_paging_does_not_skip_earlier_ones(self) -> None:
        source = IdAllowlistSource(["111"])
        client = MagicMock(spec=ZoomClient)
        base = [
            ZoomSessionOccurrence(
                uuid=f"uuid-{i:04d}", start_time=f"2026-01-01T00:{i:02d}:00Z"
            )
            for i in range(_MAX_WORK_PER_STEP + 5)
        ]
        # The meeting runs again between steps, and Zoom returns the newest
        # entry first — order the connector must not depend on.
        later = [
            ZoomSessionOccurrence(uuid="uuid-9999", start_time="2026-06-01T00:00:00Z")
        ] + base
        client.list_past_meeting_occurrences.side_effect = [base, later]

        first = source.discover_step(client, _START, _END, None)
        second = source.discover_step(client, _START, _END, first.next_cursor)

        seen = [w.occurrence_uuid for w in first.work + second.work]
        assert set(o.uuid for o in base).issubset(set(seen))
        assert len(seen) == len(set(seen))

    def test_old_cursor_without_offset_still_loads(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = _client_with_occurrences(
            [ZoomSessionOccurrence(uuid="uuid-1", start_time="2026-01-15T10:00:00Z")]
        )

        # A checkpoint written before paging existed carries only "index".
        result = source.discover_step(client, _START, _END, {"index": 1})

        assert [w.session_id for w in result.work] == ["222"]
        assert result.done is True


class TestSlowTranscriptIsRetried:
    """A transcript can be NOT_READY for hours after the meeting. Processing
    skips it, so the only thing that brings it back is the poll window still
    reaching far enough back on a later run."""

    def _still_offered_after(self, lag_hours: float) -> bool:
        source = IdAllowlistSource(["111"])
        now = time.time()
        meeting_at = now - lag_hours * _ONE_HOUR
        client = _client_with_occurrences([_occurrence_at("uuid-slow", meeting_at)])

        # window_start has advanced to just before now, the way a steady-state
        # run looks once the meeting is well in the past.
        poll_start = now - _ONE_HOUR
        result = source.discover_step(client, poll_start, now, None)
        return [w.occurrence_uuid for w in result.work] == ["uuid-slow"]

    def test_transcript_arriving_within_the_buffer_is_still_offered(self) -> None:
        buffer_hours = _OCCURRENCE_POLL_OVERLAP_SECONDS / _ONE_HOUR
        # Zoom gives no guaranteed maximum; these are lags customers report.
        for lag in (2, 12, 24, 30, buffer_hours - 1):
            assert self._still_offered_after(lag), f"lost a transcript at {lag}h"

    def test_transcript_arriving_past_the_buffer_is_lost(self) -> None:
        buffer_hours = _OCCURRENCE_POLL_OVERLAP_SECONDS / _ONE_HOUR
        # Documents the limit rather than endorsing it: past this, the meeting
        # has fallen behind the window and nothing re-offers it.
        assert not self._still_offered_after(buffer_hours + 2)


class TestBuildDiscoverySources:
    def test_no_config_yields_no_sources(self) -> None:
        assert build_discovery_sources(None) == []
        assert build_discovery_sources([]) == []
        assert build_discovery_sources([], []) == []
        assert build_discovery_sources([], [], [], None) == []

    def test_blank_host_emails_and_group_id_are_not_configuration(self) -> None:
        assert build_discovery_sources(None, None, ["  "], "  ") == []

    def test_host_emails_alone_yield_a_host_source(self) -> None:
        sources = build_discovery_sources(None, None, ["host@example.com"])
        assert len(sources) == 1
        assert isinstance(sources[0], HostAllowlistSource)

    def test_group_id_alone_yields_a_group_source(self) -> None:
        sources = build_discovery_sources(None, None, None, "group-1")
        assert len(sources) == 1
        assert isinstance(sources[0], GroupSource)

    def test_every_configured_mechanism_becomes_its_own_source(self) -> None:
        sources = build_discovery_sources(
            ["111"], ["222"], ["host@example.com"], "group-1"
        )
        assert [type(source) for source in sources] == [
            IdAllowlistSource,
            HostAllowlistSource,
            GroupSource,
        ]

    def test_meeting_ids_yield_allowlist_source(self) -> None:
        sources = build_discovery_sources(["111"])
        assert len(sources) == 1
        assert isinstance(sources[0], IdAllowlistSource)

    def test_webinar_ids_alone_still_yield_a_source(self) -> None:
        sources = build_discovery_sources(None, ["222"])
        assert len(sources) == 1
        assert isinstance(sources[0], IdAllowlistSource)

    def test_both_kinds_of_id_share_one_source(self) -> None:
        sources = build_discovery_sources(["111"], ["222"])
        assert len(sources) == 1


class TestDiscoverySystemicFailures:
    """Skipping a session it couldn't list is right for a session-specific
    error and wrong for a rate limit, which would skip every session left."""

    def test_rate_limit_stops_discovery_instead_of_skipping_the_session(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = MagicMock(spec=ZoomClient)
        response = requests.Response()
        response.status_code = 429
        client.list_past_meeting_occurrences.side_effect = requests.HTTPError(
            "429", response=response
        )

        with pytest.raises(requests.HTTPError):
            source.discover_step(client, _START, _END, None)

    def test_expired_credentials_stop_discovery(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_meeting_occurrences.side_effect = CredentialExpiredError(
            "token expired"
        )

        with pytest.raises(CredentialExpiredError):
            source.discover_step(client, _START, _END, None)

    def test_a_truncated_response_body_stops_discovery(self) -> None:
        # The occurrence listing ends in response.json(), so a truncated body
        # surfaces as this rather than as an HTTP error.
        source = IdAllowlistSource(["111", "222"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_meeting_occurrences.side_effect = (
            requests.exceptions.JSONDecodeError("truncated", "{", 1)
        )

        with pytest.raises(requests.exceptions.JSONDecodeError):
            source.discover_step(client, _START, _END, None)


class TestIdAllowlistWebinars:
    def _client_with_webinar_occurrences(
        self, occurrences: list[ZoomSessionOccurrence]
    ) -> MagicMock:
        client = MagicMock(spec=ZoomClient)
        client.list_past_webinar_occurrences.return_value = occurrences
        return client

    def test_webinar_id_is_listed_through_the_webinar_endpoint(self) -> None:
        source = IdAllowlistSource([], ["222"])
        client = self._client_with_webinar_occurrences(
            [ZoomSessionOccurrence(uuid="w-1", start_time="2026-01-15T10:00:00Z")]
        )

        result = source.discover_step(client, _START, _END, None)

        client.list_past_webinar_occurrences.assert_called_once_with("222")
        client.list_past_meeting_occurrences.assert_not_called()
        work = result.work[0]
        assert work.session_type == ZoomSessionType.WEBINAR
        assert work.session_id == "222"
        assert work.occurrence_uuid == "w-1"

    def test_meetings_run_before_webinars_in_one_cursor_walk(self) -> None:
        source = IdAllowlistSource(["111"], ["222"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_meeting_occurrences.return_value = [
            ZoomSessionOccurrence(uuid="m-1", start_time="2026-01-15T10:00:00Z")
        ]
        client.list_past_webinar_occurrences.return_value = [
            ZoomSessionOccurrence(uuid="w-1", start_time="2026-01-16T10:00:00Z")
        ]

        first = source.discover_step(client, _START, _END, None)
        second = source.discover_step(client, _START, _END, first.next_cursor)

        assert [(w.session_type, w.occurrence_uuid) for w in first.work] == [
            (ZoomSessionType.MEETING, "m-1")
        ]
        assert [(w.session_type, w.occurrence_uuid) for w in second.work] == [
            (ZoomSessionType.WEBINAR, "w-1")
        ]
        assert second.done is True

    def test_failure_names_the_webinar_rather_than_the_bare_id(self) -> None:
        source = IdAllowlistSource([], ["111"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_webinar_occurrences.side_effect = RuntimeError("boom")

        result = source.discover_step(client, _START, _END, None)

        assert result.failures[0].failed_entity is not None
        assert result.failures[0].failed_entity.entity_id == "webinar:111"

    def test_a_missing_add_on_stops_discovery_instead_of_skipping_webinars(
        self,
    ) -> None:
        # Without the add-on every webinar call fails, so skipping this one
        # silently skips them all and still reports success.
        source = IdAllowlistSource([], ["222", "333"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_webinar_occurrences.side_effect = InsufficientPermissionsError(
            "no add-on"
        )

        with pytest.raises(InsufficientPermissionsError):
            source.discover_step(client, _START, _END, None)


def _recording(
    uuid: str,
    session_id: int | str = 6840331990,
    topic: str | None = "Weekly Sync",
    start_time: str | None = "2026-01-15T10:00:00Z",
    recording_type: str = "2",
) -> ZoomRecordingEntry:
    return ZoomRecordingEntry(
        uuid=uuid,
        id=session_id,
        topic=topic,
        start_time=start_time,
        type=recording_type,
    )


def _client_for_hosts(
    users: list[ZoomUser] | None = None,
    members: list[ZoomUser] | None = None,
    recordings: list[ZoomRecordingEntry] | None = None,
) -> MagicMock:
    client = MagicMock(spec=ZoomClient)
    client.list_users.return_value = ZoomUserPage(users=users or [])
    client.list_group_members.return_value = ZoomUserPage(users=members or [])
    client.list_user_recordings.return_value = ZoomRecordingPage(
        recordings=recordings or []
    )
    return client


class TestHostAllowlistSource:
    def test_an_email_is_resolved_to_a_user_id_before_recordings_are_listed(
        self,
    ) -> None:
        source = HostAllowlistSource(["host@example.com"])
        client = _client_for_hosts(
            users=[
                ZoomUser(id="other", email="someone@example.com"),
                ZoomUser(id="u1", email="host@example.com"),
            ],
            recordings=[_recording("uuid-1")],
        )

        result = source.discover_step(client, _START, _END, None)

        assert client.list_user_recordings.call_args.kwargs["user_id"] == "u1"
        assert [w.occurrence_uuid for w in result.work] == ["uuid-1"]
        assert result.done is True

    def test_work_carries_everything_processing_would_otherwise_refetch(self) -> None:
        source = HostAllowlistSource(["host@example.com"])
        client = _client_for_hosts(
            users=[ZoomUser(id="u1", email="host@example.com")],
            recordings=[_recording("uuid-1")],
        )

        work = source.discover_step(client, _START, _END, None).work[0]

        assert work.session_type == ZoomSessionType.MEETING
        assert work.session_id == "6840331990"
        assert work.occurrence_uuid == "uuid-1"
        assert work.topic == "Weekly Sync"
        assert work.start_time == "2026-01-15T10:00:00Z"

    def test_email_matching_ignores_case_and_padding(self) -> None:
        source = HostAllowlistSource(["  Host@Example.com "])
        client = _client_for_hosts(
            users=[ZoomUser(id="u1", email="host@example.com")],
            recordings=[_recording("uuid-1")],
        )

        result = source.discover_step(client, _START, _END, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-1"]

    def test_an_unknown_email_is_reported_rather_than_silently_skipped(self) -> None:
        source = HostAllowlistSource(["typo@example.com"])
        client = _client_for_hosts(users=[ZoomUser(id="u1", email="host@example.com")])

        result = source.discover_step(client, _START, _END, None)

        assert result.work == []
        assert len(result.failures) == 1
        failure = result.failures[0]
        assert failure.failed_entity is not None
        assert failure.failed_entity.entity_id == "host:typo@example.com"
        assert result.done is True

    def test_a_host_who_has_not_accepted_their_invitation_is_reported(self) -> None:
        source = HostAllowlistSource(["pending@example.com"])
        client = _client_for_hosts(users=[ZoomUser(email="pending@example.com")])

        result = source.discover_step(client, _START, _END, None)

        assert result.failures[0].failed_entity is not None
        assert result.failures[0].failed_entity.entity_id == "host:pending@example.com"
        client.list_user_recordings.assert_not_called()

    def test_user_paging_stops_as_soon_as_every_email_is_found(self) -> None:
        source = HostAllowlistSource(["host@example.com"])
        client = _client_for_hosts(recordings=[_recording("uuid-1")])
        client.list_users.side_effect = [
            ZoomUserPage(
                users=[ZoomUser(id="u1", email="host@example.com")],
                next_page_token="tok",
            ),
            ZoomUserPage(users=[ZoomUser(id="u2", email="another@example.com")]),
        ]

        source.discover_step(client, _START, _END, None)

        assert client.list_users.call_count == 1

    def test_user_paging_continues_until_an_email_is_found(self) -> None:
        source = HostAllowlistSource(["host@example.com"])
        client = _client_for_hosts(recordings=[_recording("uuid-1")])
        client.list_users.side_effect = [
            ZoomUserPage(
                users=[ZoomUser(id="u2", email="another@example.com")],
                next_page_token="tok",
            ),
            ZoomUserPage(users=[ZoomUser(id="u1", email="host@example.com")]),
        ]

        result = source.discover_step(client, _START, _END, None)

        assert client.list_users.call_args.kwargs["page_token"] == "tok"
        assert [w.occurrence_uuid for w in result.work] == ["uuid-1"]

    def test_hosts_are_resolved_once_for_the_whole_run(self) -> None:
        source = HostAllowlistSource(["a@example.com", "b@example.com"])
        client = _client_for_hosts(
            users=[
                ZoomUser(id="u1", email="a@example.com"),
                ZoomUser(id="u2", email="b@example.com"),
            ],
            recordings=[_recording("uuid-1")],
        )

        first = source.discover_step(client, _START, _END, None)
        source.discover_step(client, _START, _END, first.next_cursor)

        assert client.list_users.call_count == 1

    def test_a_resolution_failure_is_reported_once_not_on_every_step(self) -> None:
        source = HostAllowlistSource(["typo@example.com", "host@example.com"])
        client = _client_for_hosts(
            users=[ZoomUser(id="u1", email="host@example.com")],
            recordings=[_recording("uuid-1")],
        )

        first = source.discover_step(client, _START, _END, None)
        second = source.discover_step(client, _START, _END, first.next_cursor)

        assert len(first.failures) == 1
        assert second.failures == []


class TestGroupSource:
    def test_each_member_is_crawled_in_turn(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[
                ZoomUser(id="u1", email="jill@example.com"),
                ZoomUser(id="u2", email="jack@example.com"),
            ]
        )
        client.list_user_recordings.side_effect = lambda user_id, **_: (
            ZoomRecordingPage(recordings=[_recording(f"uuid-{user_id}")])
        )

        first = source.discover_step(client, _START, _END, None)
        second = source.discover_step(client, _START, _END, first.next_cursor)

        assert [w.occurrence_uuid for w in first.work] == ["uuid-u1"]
        assert first.done is False
        assert [w.occurrence_uuid for w in second.work] == ["uuid-u2"]
        assert second.done is True
        assert second.next_cursor is None

    def test_members_are_walked_in_a_stable_order(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(id="u2"), ZoomUser(id="u1")],
            recordings=[_recording("uuid-1")],
        )

        source.discover_step(client, _START, _END, None)

        assert client.list_user_recordings.call_args.kwargs["user_id"] == "u1"

    def test_member_paging_collects_every_page(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(recordings=[_recording("uuid-1")])
        client.list_group_members.side_effect = [
            ZoomUserPage(users=[ZoomUser(id="u1")], next_page_token="tok"),
            ZoomUserPage(users=[ZoomUser(id="u2")]),
        ]

        first = source.discover_step(client, _START, _END, None)

        assert client.list_group_members.call_count == 2
        assert first.done is False
        assert first.next_cursor == {"host_index": 1}

    def test_an_empty_group_completes_without_crawling(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(members=[])

        result = source.discover_step(client, _START, _END, None)

        assert result.work == []
        assert result.done is True
        client.list_user_recordings.assert_not_called()

    def test_a_member_without_a_user_id_is_skipped(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(email="pending@example.com"), ZoomUser(id="u1")],
            recordings=[_recording("uuid-1")],
        )

        result = source.discover_step(client, _START, _END, None)

        assert client.list_user_recordings.call_count == 1
        assert result.done is True

    def test_a_broken_group_lookup_names_the_group(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts()
        client.list_group_members.side_effect = RuntimeError("boom")

        result = source.discover_step(client, _START, _END, None)

        assert result.failures[0].failed_entity is not None
        assert result.failures[0].failed_entity.entity_id == "group:group-1"
        assert result.done is True


class TestUserRecordingsPaging:
    def test_zooms_own_page_token_is_carried_in_the_cursor(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(members=[ZoomUser(id="u1")])
        client.list_user_recordings.side_effect = [
            ZoomRecordingPage(recordings=[_recording("uuid-1")], next_page_token="tok"),
            ZoomRecordingPage(recordings=[_recording("uuid-2")]),
        ]

        first = source.discover_step(client, _START, _END, None)
        assert first.next_cursor == {"host_index": 0, "page_token": "tok"}
        assert first.done is False

        second = source.discover_step(client, _START, _END, first.next_cursor)

        assert client.list_user_recordings.call_args.kwargs["page_token"] == "tok"
        assert [w.occurrence_uuid for w in second.work] == ["uuid-2"]
        assert second.done is True

    def test_pages_are_small_enough_to_outlive_zooms_token_expiry(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(members=[ZoomUser(id="u1")])

        source.discover_step(client, _START, _END, None)

        page_size = client.list_user_recordings.call_args.kwargs["page_size"]
        assert page_size == _RECORDINGS_PAGE_SIZE
        assert page_size <= _MAX_WORK_PER_STEP

    def test_an_unrecognised_cursor_restarts_rather_than_skipping_a_host(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(id="u1")], recordings=[_recording("uuid-1")]
        )

        result = source.discover_step(client, _START, _END, {"bogus": "value"})

        assert [w.occurrence_uuid for w in result.work] == ["uuid-1"]

    def test_a_cursor_past_the_last_host_is_done(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(members=[ZoomUser(id="u1")])

        result = source.discover_step(client, _START, _END, {"host_index": 5})

        assert result.work == []
        assert result.done is True
        client.list_user_recordings.assert_not_called()


class TestUserRecordingsPollWindow:
    """This endpoint takes the window itself, so nothing is filtered client-side."""

    def _window(self, client: MagicMock) -> tuple[str, str]:
        kwargs = client.list_user_recordings.call_args.kwargs
        return kwargs["from_date"].isoformat(), kwargs["to_date"].isoformat()

    def test_the_poll_window_is_pushed_to_zoom_as_dates(self) -> None:
        # The expected start is three days before the poll start: that is the
        # default 72-hour lag buffer, not an arbitrary date.
        source = GroupSource("group-1")
        client = _client_for_hosts(members=[ZoomUser(id="u1")])
        start = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc).timestamp()
        end = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc).timestamp()

        source.discover_step(client, start, end, None)

        assert self._window(client) == ("2026-03-07", "2026-03-17")

    def test_a_first_run_never_asks_for_a_date_before_the_epoch(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(members=[ZoomUser(id="u1")])

        source.discover_step(client, 0, _END, None)

        assert self._window(client)[0] == "1970-01-01"

    def test_an_occurrence_outside_the_window_is_zooms_call_not_ours(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(id="u1")],
            recordings=[_recording("uuid-1", start_time="1999-01-01T10:00:00Z")],
        )

        result = source.discover_step(client, time.time() - 60, time.time(), None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-1"]


class TestUserRecordingsSessionTypes:
    def test_a_webinar_recording_is_tagged_as_a_webinar(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(id="u1")],
            recordings=[_recording("uuid-1", recording_type="5")],
        )

        work = source.discover_step(client, _START, _END, None).work[0]

        assert work.session_type == ZoomSessionType.WEBINAR

    def test_a_portal_upload_is_not_a_session_and_is_skipped(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(id="u1")],
            recordings=[
                _recording("uuid-upload", recording_type="99"),
                _recording("uuid-meeting"),
            ],
        )

        result = source.discover_step(client, _START, _END, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-meeting"]

    def test_a_code_zoom_added_later_is_skipped_rather_than_guessed_at(self) -> None:
        # Indexing it as a meeting would freeze that guess into the document id
        # and into which access-list endpoint ticket 04 calls for it.
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(id="u1")],
            recordings=[
                _recording("uuid-new-kind", recording_type="42"),
                _recording("uuid-meeting"),
            ],
        )

        result = source.discover_step(client, _START, _END, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-meeting"]

    def test_a_recording_with_no_type_at_all_is_skipped(self) -> None:
        # No field in this response is marked required, so a missing type is
        # possible and is not evidence that the session was a meeting.
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[ZoomUser(id="u1")],
            recordings=[
                ZoomRecordingEntry(uuid="uuid-typeless", id=111, topic="Mystery")
            ],
        )

        result = source.discover_step(client, _START, _END, None)

        assert result.work == []


class TestUserRecordingsFailures:
    def test_one_broken_host_does_not_cost_the_next_one(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(
            members=[
                ZoomUser(id="u1", email="jill@example.com"),
                ZoomUser(id="u2", email="jack@example.com"),
            ]
        )

        def _recordings(user_id: str, **_: object) -> ZoomRecordingPage:
            if user_id == "u1":
                raise RuntimeError("boom")
            return ZoomRecordingPage(recordings=[_recording("uuid-2")])

        client.list_user_recordings.side_effect = _recordings

        first = source.discover_step(client, _START, _END, None)
        second = source.discover_step(client, _START, _END, first.next_cursor)

        assert first.work == []
        assert first.failures[0].failed_entity is not None
        assert first.failures[0].failed_entity.entity_id == "host:jill@example.com"
        missed = first.failures[0].failed_entity.missed_time_range
        assert missed is not None
        assert missed[0].timestamp() == _START - _OCCURRENCE_POLL_OVERLAP_SECONDS
        assert missed[1].timestamp() == _END
        assert [w.occurrence_uuid for w in second.work] == ["uuid-2"]

    def test_a_rate_limit_stops_discovery_instead_of_skipping_the_host(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts(members=[ZoomUser(id="u1"), ZoomUser(id="u2")])
        response = requests.Response()
        response.status_code = 429
        client.list_user_recordings.side_effect = requests.HTTPError(
            "429", response=response
        )

        with pytest.raises(requests.HTTPError):
            source.discover_step(client, _START, _END, None)

    def test_a_rate_limit_while_resolving_stops_discovery(self) -> None:
        source = GroupSource("group-1")
        client = _client_for_hosts()
        response = requests.Response()
        response.status_code = 429
        client.list_group_members.side_effect = requests.HTTPError(
            "429", response=response
        )

        with pytest.raises(requests.HTTPError):
            source.discover_step(client, _START, _END, None)

    def test_a_missing_scope_stops_discovery_rather_than_emptying_the_group(
        self,
    ) -> None:
        # Without group:read:admin every group resolves to nobody, so reporting
        # this per group would finish the run successfully having indexed nothing.
        source = GroupSource("group-1")
        client = _client_for_hosts()
        client.list_group_members.side_effect = InsufficientPermissionsError(
            "missing group:read:admin"
        )

        with pytest.raises(InsufficientPermissionsError):
            source.discover_step(client, _START, _END, None)

    def test_expired_credentials_while_resolving_stop_discovery(self) -> None:
        source = HostAllowlistSource(["host@example.com"])
        client = _client_for_hosts()
        client.list_users.side_effect = CredentialExpiredError("token expired")

        with pytest.raises(CredentialExpiredError):
            source.discover_step(client, _START, _END, None)
