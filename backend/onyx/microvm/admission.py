"""Admission helpers with no agent dependency (safe to import on the pod path)."""

import random

from onyx.microvm.configs import (
    FIRECRACKER_ENABLED,
    SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS,
)


def scheduled_run_jitter_seconds(rng: random.Random | None = None) -> float:
    """Delay for one scheduled-task run of a beat tick. 0 unless Firecracker."""
    if not FIRECRACKER_ENABLED or SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS <= 0:
        return 0.0
    return (rng or random).uniform(0, SANDBOX_FC_SCHEDULED_RUN_JITTER_SECONDS)
