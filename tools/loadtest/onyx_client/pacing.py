"""Deterministic user schedules, independent of completion order."""

from __future__ import annotations

import hashlib
import random


def user_seed(seed: int, worker: int, user: int) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{seed}:{worker}:{user}".encode()).digest()[:8], "big"
    )


def question_order(count: int, seed: int) -> list[int]:
    indices = list(range(count))
    random.Random(seed).shuffle(indices)
    return indices


def pause_seconds(mean: float, jitter: float, seed: int, turn: int) -> float:
    if mean < 0 or not 0 <= jitter <= 1:
        raise ValueError(
            "Think time must be nonnegative; jitter must be between 0 and 1"
        )
    return mean * (
        1 + jitter * (2 * random.Random(user_seed(seed, 0, turn)).random() - 1)
    )
