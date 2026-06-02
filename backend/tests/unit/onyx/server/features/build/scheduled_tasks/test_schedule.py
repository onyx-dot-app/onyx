from datetime import datetime
from datetime import timezone

from onyx.server.features.build.scheduled_tasks.schedule import compute_next_run_at
from onyx.server.features.build.scheduled_tasks.schedule import human_readable
from onyx.server.features.build.scheduled_tasks.schedule import next_n_fires


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


def test_human_readable_does_not_append_timezone() -> None:
    description = human_readable("0 9 * * 1")

    assert "UTC" not in description
