"""Unit tests for event loop lag probe."""

import asyncio
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.server.metrics.event_loop_lag import _probe_loop
from onyx.server.metrics.event_loop_lag import start_event_loop_lag_probe
from onyx.server.metrics.event_loop_lag import stop_event_loop_lag_probe


@pytest.mark.asyncio
@patch("onyx.server.metrics.event_loop_lag._LAG")
@patch("onyx.server.metrics.event_loop_lag._LAG_MAX")
async def test_probe_measures_lag(
    mock_lag_max: MagicMock,  # noqa: ARG001
    mock_lag: MagicMock,
) -> None:
    """Verify the probe records non-negative lag after sleeping."""
    import onyx.server.metrics.event_loop_lag as mod

    original_lag = mod._current_lag
    original_max = mod._max_lag
    mod._current_lag = 0.0
    mod._max_lag = 0.0

    try:
        # Run the probe with a very short interval so it fires quickly
        task = asyncio.create_task(_probe_loop(0.01))
        await asyncio.sleep(0.05)  # Let it fire a few times
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # The lag gauge should have been set at least once
        assert mock_lag.set.call_count >= 1
        # All observed lag values should be non-negative
        for call in mock_lag.set.call_args_list:
            assert call[0][0] >= 0.0
    finally:
        mod._current_lag = original_lag
        mod._max_lag = original_max


@pytest.mark.asyncio
async def test_start_stop_lifecycle() -> None:
    """Verify start/stop create and cancel the task."""
    import onyx.server.metrics.event_loop_lag as mod

    original_task = mod._probe_task
    mod._probe_task = None

    try:
        with patch(
            "onyx.server.metrics.event_loop_lag.EVENT_LOOP_LAG_PROBE_INTERVAL_SECONDS",
            0.01,
        ):
            start_event_loop_lag_probe()
            assert mod._probe_task is not None
            assert not mod._probe_task.cancelled()

            await stop_event_loop_lag_probe()
            assert mod._probe_task is None
    finally:
        mod._probe_task = original_task
