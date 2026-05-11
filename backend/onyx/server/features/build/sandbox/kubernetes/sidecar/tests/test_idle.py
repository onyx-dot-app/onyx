from __future__ import annotations

import time

from app.idle import IdleTracker


def test_idle_tracker_touch_resets_timer() -> None:
    tracker = IdleTracker(idle_timeout_seconds=10, check_interval_seconds=1)
    before = tracker.seconds_since_last_interaction()
    time.sleep(0.05)
    after = tracker.seconds_since_last_interaction()
    assert after > before

    tracker.touch()
    assert tracker.seconds_since_last_interaction() < after


def test_idle_tracker_is_idle_after_threshold() -> None:
    tracker = IdleTracker(idle_timeout_seconds=0, check_interval_seconds=1)
    # threshold=0 means is_idle is true immediately
    assert tracker.is_idle()


def test_healthz_request_does_not_bump_idle_timer(client) -> None:
    tracker = client.app.state.idle
    tracker._last_interaction -= 100  # type: ignore[attr-defined]
    before = tracker.seconds_since_last_interaction()
    client.get("/healthz")
    after = tracker.seconds_since_last_interaction()
    assert after >= before  # never reset
