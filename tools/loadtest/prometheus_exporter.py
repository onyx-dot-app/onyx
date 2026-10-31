"""Locust integration for the Prometheus collector.

Imported for its side effect (the init listener) by locustfile.py. On the
master/standalone runner it registers the collector and serves /metrics on a
dedicated port (default 9646; set LOCUST_PROMETHEUS_PORT to override) so chat
milestone latency / failure rate can be overlaid against server-side metrics
in Grafana (see dashboards/). No-ops on workers, which lack aggregated stats.

The collector itself lives in prometheus_collector.py (locust-free, so it
stays gevent-free and unit-testable).
"""

from __future__ import annotations

import os
from typing import Any

from locust import events
from locust.runners import WorkerRunner
from onyx_client import workload_metrics
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY
from prometheus_collector import LocustCollector

METRICS_PORT = int(os.environ.get("LOCUST_PROMETHEUS_PORT", "9646"))

_started = False


def _start_prometheus(environment: Any, **_kwargs: Any) -> None:
    global _started
    # Workers don't hold aggregated stats; only export from master/standalone.
    if isinstance(environment.runner, WorkerRunner) or _started:
        return
    REGISTRY.register(LocustCollector(environment))
    start_http_server(METRICS_PORT)
    _started = True


# Cumulative workload metrics survive Locust's statistics reset. Start a new
# test to reset them; compare interval deltas when excluding warmup.


def _reset_workload(**_kwargs: Any) -> None:
    workload_metrics.reset()


def _report_workload(data: dict[str, Any], **_kwargs: Any) -> None:
    data["onyx_workload"] = workload_metrics.snapshot()


def _receive_workload(client_id: str, data: dict[str, Any], **_kwargs: Any) -> None:
    workload_metrics.workers[client_id] = data.get("onyx_workload", {})


events.init.add_listener(_start_prometheus)
events.test_start.add_listener(_reset_workload)
events.report_to_master.add_listener(_report_workload)
events.worker_report.add_listener(_receive_workload)
