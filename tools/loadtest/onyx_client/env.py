"""Small env-var parsing helpers shared across users and scenarios."""

from __future__ import annotations

import os


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default
