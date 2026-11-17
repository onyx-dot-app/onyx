"""Code mode capacity metrics, read from the default registry."""

from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from onyx.server.metrics import code_mode as metrics
from onyx.tools.tool_implementations.code_mode import sandbox


def _value(name: str) -> float:
    return REGISTRY.get_sample_value(name, {}) or 0.0


def test_the_pool_sets_every_limit_gauge(monkeypatch: pytest.MonkeyPatch) -> None:
    for gauge in (
        metrics.SANDBOX_WORKERS_LIMIT,
        metrics.SUSPENDED_BYTES_LIMIT,
        metrics.TOOL_CALL_THREADS_LIMIT,
        metrics.CELLS_LIMIT,
    ):
        gauge.set(0)
    monkeypatch.setattr(sandbox, "_pool", None)
    with patch.object(sandbox, "Monty"):
        sandbox.sandbox_pool()
    assert _value("onyx_code_mode_sandbox_workers_limit") == (
        sandbox.MAX_SANDBOX_PROCESSES
    )
    assert _value("onyx_code_mode_suspended_bytes_limit") == (
        sandbox.MAX_SUSPENDED_BYTES
    )
    assert _value("onyx_code_mode_tool_call_threads_limit") == (
        sandbox.MAX_TOOL_CALL_THREADS
    )
    assert _value("onyx_code_mode_cells_limit") == sandbox.MAX_RUNNING_CELLS


def test_program_duration_buckets_resolve_seconds_near_the_typical_p95() -> None:
    bounds = {
        float(sample.labels["le"])
        for family in metrics.PROGRAM_DURATION.collect()
        for sample in family.samples
        if sample.name.endswith("_bucket")
    }
    assert {2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0} <= bounds
