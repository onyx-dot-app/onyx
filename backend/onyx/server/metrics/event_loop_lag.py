"""Event loop lag probe.

Schedules a periodic asyncio task that measures the delta between
expected and actual wakeup time. If the event loop is blocked by
synchronous code or CPU-bound work, the lag will spike.

Metrics:
- onyx_api_event_loop_lag_seconds: Current measured lag
- onyx_api_event_loop_lag_max_seconds: Max observed lag since start
"""

import asyncio

from prometheus_client import Gauge

from onyx.configs.app_configs import EVENT_LOOP_LAG_PROBE_INTERVAL_SECONDS
from onyx.utils.logger import setup_logger

logger = setup_logger()

_LAG = Gauge(
    "onyx_api_event_loop_lag_seconds",
    "Event loop scheduling lag in seconds",
)

_LAG_MAX = Gauge(
    "onyx_api_event_loop_lag_max_seconds",
    "Maximum event loop scheduling lag observed since process start",
)

_probe_task: asyncio.Task[None] | None = None
_current_lag: float = 0.0
_max_lag: float = 0.0


async def _probe_loop(interval: float) -> None:
    global _current_lag, _max_lag
    loop = asyncio.get_running_loop()

    while True:
        before = loop.time()
        await asyncio.sleep(interval)
        after = loop.time()

        try:
            lag = (after - before) - interval
            if lag < 0:
                lag = 0.0

            _current_lag = lag
            _LAG.set(lag)
            if lag > _max_lag:
                _max_lag = lag
                _LAG_MAX.set(_max_lag)
        except Exception:
            logger.warning(
                "Error in event loop lag probe, skipping iteration",
                exc_info=True,
            )


def get_current_lag() -> float:
    """Return the last measured lag value."""
    return _current_lag


def get_max_lag() -> float:
    """Return the max observed lag since process start."""
    return _max_lag


def start_event_loop_lag_probe() -> None:
    """Start the background lag measurement task."""
    global _probe_task
    if _probe_task is not None:
        return
    _probe_task = asyncio.create_task(
        _probe_loop(EVENT_LOOP_LAG_PROBE_INTERVAL_SECONDS)
    )


async def stop_event_loop_lag_probe() -> None:
    """Cancel the background lag measurement task and await cleanup."""
    global _probe_task
    if _probe_task is not None:
        _probe_task.cancel()
        try:
            await _probe_task
        except asyncio.CancelledError:
            pass
        _probe_task = None
