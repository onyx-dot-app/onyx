"""Staged ramp for collapse-point hunting.

StepRampShape holds the user count at successive plateaus so the knee where
the system stops keeping up is visible in the timeline. Opt-in only: the
locustfile binds it when ONYX_SHAPE=stepramp, since Locust auto-activates any
shape it finds and overrides -u/-r. Tune via ONYX_RAMP_STAGES / _DWELL /
_SPAWN (see README).
"""

from __future__ import annotations

import os

from locust import LoadTestShape

_DEFAULT_STAGES = "25,50,100,200"


def _stage_users() -> list[int]:
    raw = os.environ.get("ONYX_RAMP_STAGES", _DEFAULT_STAGES)
    users = [int(part) for part in raw.split(",") if part.strip()]
    # Empty/garbage (e.g. ONYX_RAMP_STAGES="") would make tick() stop instantly
    # with no users ever spawned — fall back to the default instead.
    if not users:
        users = [int(p) for p in _DEFAULT_STAGES.split(",")]
    return users


class StepRampShape(LoadTestShape):
    # Clamp to sane minimums: a non-positive dwell makes end times non-increasing
    # (test stops immediately) and a non-positive spawn rate stalls spawning.
    dwell_s: int = max(1, int(os.environ.get("ONYX_RAMP_DWELL", "300")))
    spawn_rate: float = max(0.1, float(os.environ.get("ONYX_RAMP_SPAWN", "5")))

    def __init__(self) -> None:
        super().__init__()
        # (cumulative_end_time, users) plateaus.
        self._stages: list[tuple[float, int]] = []
        end = 0.0
        for count in _stage_users():
            end += self.dwell_s
            self._stages.append((end, count))

    def tick(self) -> tuple[int, float] | None:
        run_time = self.get_run_time()
        for end, count in self._stages:
            if run_time < end:
                return count, self.spawn_rate
        return None  # past the last plateau → stop
