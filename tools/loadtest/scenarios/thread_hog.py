"""Deterministic thread-occupancy driver for the worker / threadpool sweep.

Each turn streams a deliberately slow mock response, so the api-server holds one
anyio threadpool thread (the chat stream is a sync generator) for the whole
turn. Pile up enough concurrent ThreadHogUsers and the pool saturates — the
failure mode that starves /health and triggers liveness kills. Pair with
HealthProbeUser and sweep api.workers / api.threadpoolSize / CPU to find the
concurrency a given config survives.

Default model ``mock-ttft1000-itl200-len600`` ≈ 1s + 600 × 0.2s ≈ 121s of
thread hold per turn. Override with ONYX_HOG_MODEL (mock knobs ride in the
model name; see mock_llm/app.py).
"""

from __future__ import annotations

import os

from locust import constant
from onyx_client.chat_user import OnyxChatUser
from onyx_client.env import env_float


class ThreadHogUser(OnyxChatUser):
    abstract = False
    weight = 1

    scenario_prefix: str = "hog"
    mock_model: str | None = os.environ.get(
        "ONYX_HOG_MODEL", "mock-ttft1000-itl200-len600"
    )

    # Each turn already holds a thread for ~2 min; minimal think time keeps the
    # thread occupied so concurrency maps directly to pool pressure.
    wait_time = constant(env_float("ONYX_HOG_WAIT_SECONDS", 1.0))
    stream_read_timeout: float = env_float("ONYX_HOG_STREAM_READ_TIMEOUT", 600.0)
