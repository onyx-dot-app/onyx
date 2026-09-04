import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

from onyx.connectors.zoom.client import ZoomClient
from onyx.connectors.zoom.models import ZoomMeetingOccurrence
from onyx.connectors.zoom.recordings.discovery import (
    _MAX_WORK_PER_STEP,
    _OCCURRENCE_POLL_OVERLAP_SECONDS,
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


def _occurrence_at(uuid: str, epoch_seconds: float) -> ZoomMeetingOccurrence:
    return ZoomMeetingOccurrence(
        uuid=uuid,
        start_time=datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat(),
    )


def _client_with_occurrences(
    occurrences: list[ZoomMeetingOccurrence],
) -> MagicMock:
    client = MagicMock(spec=ZoomClient)
    client.list_past_meeting_occurrences.return_value = occurrences
    return client


class TestIdAllowlistSource:
    def test_one_id_expanded_per_step_with_cursor_progression(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = MagicMock(spec=ZoomClient)
        client.list_past_meeting_occurrences.side_effect = lambda session_id: [
            ZoomMeetingOccurrence(uuid=f"uuid-{session_id}")
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
            [ZoomMeetingOccurrence(uuid="uuid-1", start_time="2026-01-15T10:00:00Z")]
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
                ZoomMeetingOccurrence(uuid="uuid-1", start_time="2026-01-01T10:00:00Z"),
                ZoomMeetingOccurrence(uuid="uuid-2", start_time="2026-01-08T10:00:00Z"),
                ZoomMeetingOccurrence(uuid="uuid-3", start_time="2026-01-15T10:00:00Z"),
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
        assert failure.failed_entity.entity_id == "111"
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
            [ZoomMeetingOccurrence(uuid="uuid-junk", start_time="not-a-date")]
        )

        # A narrow window that a real date would fall outside of: the point is
        # that a timestamp we can't read must not cost us the transcript.
        result = source.discover_step(client, now - 60, now, None)

        assert [w.occurrence_uuid for w in result.work] == ["uuid-junk"]

    def test_occurrence_without_start_time_is_never_filtered_out(self) -> None:
        source = IdAllowlistSource(["111"])
        now = time.time()
        client = _client_with_occurrences(
            [ZoomMeetingOccurrence(uuid="uuid-no-time", start_time=None)]
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
                ZoomMeetingOccurrence(
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
                ZoomMeetingOccurrence(
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
            [ZoomMeetingOccurrence(uuid="uuid-1", start_time="2026-01-15T10:00:00Z")]
        )

        # A checkpoint we can't make sense of should re-do work, never skip it.
        result = source.discover_step(client, _START, _END, {"bogus": "value"})

        assert [w.occurrence_uuid for w in result.work] == ["uuid-1"]

    def test_paging_cursor_carries_index_and_offset(self) -> None:
        source = IdAllowlistSource(["111", "222"])
        client = _client_with_occurrences(
            [
                ZoomMeetingOccurrence(
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
            ZoomMeetingOccurrence(
                uuid=f"uuid-{i:04d}", start_time=f"2026-01-01T00:{i:02d}:00Z"
            )
            for i in range(_MAX_WORK_PER_STEP + 5)
        ]
        # The meeting runs again between steps, and Zoom returns the newest
        # entry first — order the connector must not depend on.
        later = [
            ZoomMeetingOccurrence(uuid="uuid-9999", start_time="2026-06-01T00:00:00Z")
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
            [ZoomMeetingOccurrence(uuid="uuid-1", start_time="2026-01-15T10:00:00Z")]
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

    def test_meeting_ids_yield_allowlist_source(self) -> None:
        sources = build_discovery_sources(["111"])
        assert len(sources) == 1
        assert isinstance(sources[0], IdAllowlistSource)
