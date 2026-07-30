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
from prometheus_client import start_http_server
from prometheus_client.core import REGISTRY
from prometheus_collector import LocustCollector

METRICS_PORT = int(os.environ.get("LOCUST_PROMETHEUS_PORT", "9646"))

_started = False


@events.init.add_listener
def _start_prometheus(environment: Any, **_kwargs: Any) -> None:
    global _started
    # Workers don't hold aggregated stats; only export from master/standalone.
    if isinstance(environment.runner, WorkerRunner) or _started:
        return
    REGISTRY.register(LocustCollector(environment))
    start_http_server(METRICS_PORT)
    _started = True
