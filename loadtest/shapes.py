"""Load-test shapes for collapse-point hunting.

A Locust LoadTestShape drives the user count over time, overriding the manual
-u/-r controls. Onyx only activates one when ONYX_SHAPE is set (the locustfile
binds the class conditionally) — by default runs use a fixed user count.

StepRampShape walks the user count up through a series of plateaus, holding
each long enough for latency/throughput to settle, so the knee where the
system stops keeping up is visible in the timeline rather than guessed at.
Pair it with the slow-provider mock profile (mock-ttft8000-itl40-len600) to
hold streams open and surface connection/memory exhaustion sooner.

Tuning (env):
    ONYX_RAMP_STAGES   comma-separated user counts (default "25,50,100,200")
    ONYX_RAMP_DWELL    seconds to hold each stage (default 300)
    ONYX_RAMP_SPAWN    users spawned per second at each step (default 5)
"""

from __future__ import annotations

import os

from locust import LoadTestShape


def _stage_users() -> list[int]:
    raw = os.environ.get("ONYX_RAMP_STAGES", "25,50,100,200")
    return [int(part) for part in raw.split(",") if part.strip()]


class StepRampShape(LoadTestShape):
    dwell_s: int = int(os.environ.get("ONYX_RAMP_DWELL", "300"))
    spawn_rate: float = float(os.environ.get("ONYX_RAMP_SPAWN", "5"))

    def __init__(self) -> None:
        super().__init__()
        users = _stage_users()
        # Precompute (cumulative_end_time, users) plateaus.
        self._stages: list[tuple[float, int]] = []
        end = 0.0
        for count in users:
            end += self.dwell_s
            self._stages.append((end, count))

    def tick(self) -> tuple[int, float] | None:
        run_time = self.get_run_time()
        for end, count in self._stages:
            if run_time < end:
                return count, self.spawn_rate
        # Past the last plateau: stop, which ends the run.
        return None
