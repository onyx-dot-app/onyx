from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from contextlib import suppress

logger = logging.getLogger(__name__)

# Paths that should NOT bump the idle timer. Probes are not "user activity."
NON_INTERACTIVE_PATHS = frozenset({"/healthz", "/readyz"})


class IdleTracker:
    """Tracks the most-recent authenticated interaction and triggers shutdown when idle.

    A single instance lives on `app.state.idle` and is updated by middleware on
    every successful (non-health) request. A background task polls the timestamp
    and, when the threshold is exceeded, raises SIGTERM so the FastAPI lifespan's
    shutdown path runs (preStop snapshot, clean exit).
    """

    def __init__(
        self, *, idle_timeout_seconds: int, check_interval_seconds: int
    ) -> None:
        self._idle_timeout = idle_timeout_seconds
        self._check_interval = check_interval_seconds
        self._last_interaction = time.monotonic()
        self._shutdown_triggered = False

    def touch(self) -> None:
        self._last_interaction = time.monotonic()

    def seconds_since_last_interaction(self) -> float:
        return time.monotonic() - self._last_interaction

    def is_idle(self) -> bool:
        return self.seconds_since_last_interaction() >= self._idle_timeout

    async def run(self) -> None:
        """Background loop. Cancel-safe."""
        try:
            while True:
                await asyncio.sleep(self._check_interval)
                if self.is_idle() and not self._shutdown_triggered:
                    self._shutdown_triggered = True
                    logger.info(
                        "Sidecar idle for %.1fs (threshold %ds); raising SIGTERM",
                        self.seconds_since_last_interaction(),
                        self._idle_timeout,
                    )
                    # SIGTERM lets FastAPI's lifespan shutdown run cleanly.
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
        except asyncio.CancelledError:
            # Normal during shutdown.
            raise


async def cancel_idle_task(task: asyncio.Task[None]) -> None:
    """Helper: cancel and await the background idle task during shutdown."""
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
