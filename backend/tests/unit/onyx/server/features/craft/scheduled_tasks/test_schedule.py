from datetime import datetime, timedelta, timezone
from itertools import pairwise
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from onyx.server.features.build.scheduled_tasks import schedule
from onyx.server.features.build.scheduled_tasks.schedule import (
    compute_next_dispatch_at,
    compute_next_run_at,
    next_n_fires,
    offset_seconds,
)


def test_compute_next_run_at_uses_utc_cron_fields() -> None:
    after = datetime(2026, 5, 25, 8, 59, tzinfo=timezone.utc)

    assert compute_next_run_at("0 9 * * *", after) == datetime(
        2026, 5, 25, 9, 0, tzinfo=timezone.utc
    )


def test_compute_next_run_at_treats_naive_after_as_utc() -> None:
    after = datetime(2026, 5, 25, 9, 0)

    assert compute_next_run_at("0 9 * * *", after) == datetime(
        2026, 5, 26, 9, 0, tzinfo=timezone.utc
    )


def test_next_n_fires_returns_aware_utc_datetimes() -> None:
    after = datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)

    fires = next_n_fires("*/15 * * * *", after, 3)

    assert fires == [
        datetime(2026, 5, 25, 9, 15, tzinfo=timezone.utc),
        datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc),
        datetime(2026, 5, 25, 9, 45, tzinfo=timezone.utc),
    ]


_TASK_ID = UUID("8a6e0f2c-3b1d-4c5e-9f7a-0123456789ab")


@patch.object(schedule, "SCHEDULED_TASK_FIRE_WINDOW_SECONDS", 300)
def test_offset_is_stable_per_task_and_inside_the_window() -> None:
    offsets = [offset_seconds(uuid4()) for _ in range(200)]

    assert offset_seconds(_TASK_ID) == offset_seconds(UUID(str(_TASK_ID)))
    assert all(0 <= offset < 300 for offset in offsets)
    assert len(set(offsets)) > 1


def test_offset_is_zero_when_the_window_is_off() -> None:
    with patch.object(schedule, "SCHEDULED_TASK_FIRE_WINDOW_SECONDS", 0):
        assert offset_seconds(_TASK_ID) == 0
        assert compute_next_dispatch_at(
            "0 9 * * *", datetime(2026, 5, 25, 8, 0, tzinfo=timezone.utc), _TASK_ID
        ) == datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc)


def _dispatches(
    cron: str, start: datetime, count: int, task_id: UUID
) -> list[datetime]:
    """Advance the way the dispatcher does: from the moment the run is due."""
    fires: list[datetime] = []
    after = start
    handled: datetime | None = None
    for _ in range(count):
        nxt = compute_next_dispatch_at(cron, after, task_id, handled)
        assert nxt > after
        fires.append(nxt)
        after = handled = nxt
    return fires


@pytest.mark.parametrize(
    ("cron", "step"),
    [("* * * * *", timedelta(minutes=1)), ("0 9 * * *", timedelta(days=1))],
)
def test_the_offset_keeps_every_fire(cron: str, step: timedelta) -> None:
    start = datetime(2026, 5, 25, 8, 59, 30, tzinfo=timezone.utc)

    for task_id in [uuid4() for _ in range(20)] + [_TASK_ID]:
        offset = timedelta(seconds=offset_seconds(task_id))
        dispatches = _dispatches(cron, start, 30, task_id)
        first = dispatches[0] - offset

        assert [d - offset for d in dispatches] == [first] + next_n_fires(
            cron, first, 29
        )
        assert all(b - a == step for a, b in pairwise(dispatches))


@pytest.mark.parametrize("cron", ["* * * * *", "*/15 * * * *", "0 9 * * *"])
def test_the_next_dispatch_is_always_after_now(cron: str) -> None:
    base = datetime(2026, 5, 25, 8, 55, tzinfo=timezone.utc)
    for task_id in [uuid4() for _ in range(20)]:
        for second in range(0, 900, 7):
            after = base + timedelta(seconds=second)
            assert compute_next_dispatch_at(cron, after, task_id) > after


# offset_seconds(UUID(int=180)) == 180 with the default 300 s window.
_OFFSET_180 = UUID(int=180)


@pytest.mark.parametrize(
    ("cron", "handled", "expected"),
    [
        # A row saved without an offset fired at its cron time.
        (
            "0 9 * * *",
            datetime(2026, 5, 25, 9, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 26, 9, 3, tzinfo=timezone.utc),
        ),
        # A row saved with another offset (the window changed).
        (
            "0 9 * * *",
            datetime(2026, 5, 25, 9, 0, 40, tzinfo=timezone.utc),
            datetime(2026, 5, 26, 9, 3, tzinfo=timezone.utc),
        ),
        # A row saved with this offset.
        (
            "0 9 * * *",
            datetime(2026, 5, 25, 9, 3, tzinfo=timezone.utc),
            datetime(2026, 5, 26, 9, 3, tzinfo=timezone.utc),
        ),
        (
            "* * * * *",
            datetime(2026, 5, 25, 9, 3, tzinfo=timezone.utc),
            datetime(2026, 5, 25, 9, 4, tzinfo=timezone.utc),
        ),
    ],
)
def test_a_handled_fire_does_not_fire_again(
    cron: str, handled: datetime, expected: datetime
) -> None:
    with patch.object(schedule, "SCHEDULED_TASK_FIRE_WINDOW_SECONDS", 300):
        assert offset_seconds(_OFFSET_180) == 180
        after = handled + timedelta(seconds=5)
        assert compute_next_dispatch_at(cron, after, _OFFSET_180, handled) == expected
