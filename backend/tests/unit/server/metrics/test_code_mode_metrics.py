"""Code mode capacity metrics, read from the default registry."""

from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from onyx.server.metrics import code_mode as metrics
from onyx.tools.tool_implementations.code_mode import cells, sandbox


def _value(name: str) -> float:
    return REGISTRY.get_sample_value(name, {}) or 0.0


def test_the_pool_sets_every_limit_gauge(monkeypatch: pytest.MonkeyPatch) -> None:
    for gauge in (
        metrics.SANDBOX_WORKERS_LIMIT,
        metrics.SUSPENDED_BYTES_LIMIT,
        metrics.TOOL_CALL_THREADS_LIMIT,
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


def test_the_running_cell_limit_gauge_is_set() -> None:
    assert _value("onyx_code_mode_cells_limit") == cells.MAX_RUNNING_CELLS
