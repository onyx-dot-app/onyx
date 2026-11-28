"""Mock indexing model server for the docprocessing benchmark.

Serves the embed route of the real model server. A vector is a pure function of
its text, so two runs over the same corpus write the same index. Latency and
faults are set at run time through /_mock/config.

Standalone: imports no onyx code, so it starts fast and can run in any image
that has fastapi and uvicorn.

    uvicorn server:app --app-dir backend/tests/integration/mock_services/mock_model_server --port 9750
"""

import asyncio
import hashlib
import json
import os
import struct
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class LatencyConfig(BaseModel):
    """Seconds one embed request takes: base + per text + per 1000 characters."""

    base_ms: float = Field(default=0.0, ge=0)
    per_text_ms: float = Field(default=0.0, ge=0)
    per_1k_chars_ms: float = Field(default=0.0, ge=0)
    # Requests the server works on at one time. Others wait, as on one GPU.
    max_concurrency: int = Field(default=64, ge=1)


class FaultConfig(BaseModel):
    # A request that holds a text with one of these markers gets a 500.
    fail_text_markers: list[str] = Field(default_factory=list)
    # The next N requests get a 429.
    rate_limit_next_n: int = Field(default=0, ge=0)


class MockConfig(BaseModel):
    dim: int = Field(default=384, ge=1, le=8192)
    latency: LatencyConfig = Field(default_factory=LatencyConfig)
    faults: FaultConfig = Field(default_factory=FaultConfig)


class MockStats(BaseModel):
    requests: int = 0
    texts: int = 0
    chars: int = 0
    rate_limited: int = 0
    failed: int = 0
    peak_in_flight: int = 0
    busy_seconds: float = 0.0


class EmbedRequest(BaseModel):
    """The fields of the real EmbedRequest that the mock reads."""

    texts: list[str]


def _initial_config() -> MockConfig:
    raw = os.environ.get("MOCK_MODEL_SERVER_CONFIG")
    return MockConfig.model_validate(json.loads(raw)) if raw else MockConfig()


class _State:
    def __init__(self) -> None:
        self.config = _initial_config()
        self.stats = MockStats()
        self.in_flight = 0
        self.gate = asyncio.Semaphore(self.config.latency.max_concurrency)

    def apply(self, config: MockConfig) -> None:
        self.config = config
        self.gate = asyncio.Semaphore(config.latency.max_concurrency)


app = FastAPI()
_state = _State()


def embed_text(text: str, dim: int) -> list[float]:
    """Deterministic unit vector for *text*. Stable across platforms and runs."""
    raw = hashlib.shake_256(text.encode("utf-8")).digest(dim * 2)
    values = [value - 32767.5 for value in struct.unpack(f"<{dim}H", raw)]
    norm = sum(value * value for value in values) ** 0.5
    return [round(value / norm, 6) for value in values]


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/_mock/config")
async def get_config() -> MockConfig:
    return _state.config


@app.patch("/_mock/config")
async def patch_config(patch: dict[str, Any]) -> MockConfig:
    _state.apply(
        MockConfig.model_validate(_deep_merge(_state.config.model_dump(), patch))
    )
    return _state.config


@app.get("/_mock/stats")
async def get_stats() -> MockStats:
    return _state.stats


@app.post("/_mock/reset-stats")
async def reset_stats() -> MockStats:
    _state.stats = MockStats()
    return _state.stats


@app.post("/encoder/bi-encoder-embed", response_model=None)
async def bi_encoder_embed(request: EmbedRequest) -> JSONResponse:
    config = _state.config
    stats = _state.stats
    stats.requests += 1

    if config.faults.rate_limit_next_n > 0:
        config.faults.rate_limit_next_n -= 1
        stats.rate_limited += 1
        return JSONResponse(status_code=429, content={"detail": "mock rate limit"})

    for marker in config.faults.fail_text_markers:
        if any(marker in text for text in request.texts):
            stats.failed += 1
            return JSONResponse(
                status_code=500, content={"detail": f"mock failure: {marker}"}
            )

    chars = sum(len(text) for text in request.texts)
    stats.texts += len(request.texts)
    stats.chars += chars
    latency = config.latency
    delay_s = (
        latency.base_ms
        + latency.per_text_ms * len(request.texts)
        + latency.per_1k_chars_ms * chars / 1000
    ) / 1000

    async with _state.gate:
        _state.in_flight += 1
        stats.peak_in_flight = max(stats.peak_in_flight, _state.in_flight)
        try:
            if delay_s > 0:
                await asyncio.sleep(delay_s)  # test-flakes: allow mock latency
                stats.busy_seconds += delay_s
        finally:
            _state.in_flight -= 1

    return JSONResponse(
        content={"embeddings": [embed_text(text, config.dim) for text in request.texts]}
    )
