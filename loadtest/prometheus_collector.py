"""Prometheus collector for Locust stats — pure prometheus_client, no locust
import (so it stays gevent-free and unit-testable alongside the fastapi tests).

The locust integration (init listener + http server) lives in
prometheus_exporter.py, which is imported by locustfile.py for its side effect.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from prometheus_client.core import CounterMetricFamily
from prometheus_client.core import GaugeMetricFamily

_LABELS = ["name", "method"]


def _percentile(entry: Any, pct: float) -> float:
    # Prefer the sliding-window value (better for time-series correlation);
    # fall back to all-time when the response-times cache isn't populated.
    val = entry.get_current_response_time_percentile(pct)
    if val is None:
        val = entry.get_response_time_percentile(pct) or 0
    return float(val)


class LocustCollector:
    """Pulls current aggregated stats from the runner at scrape time."""

    def __init__(self, environment: Any) -> None:
        self.environment = environment

    def collect(self) -> Iterator[Any]:
        runner = self.environment.runner
        if runner is None:
            return

        users = GaugeMetricFamily("locust_users", "Current number of users")
        users.add_metric([], runner.user_count)
        yield users

        reqs = CounterMetricFamily(
            "locust_requests_total", "Total requests", labels=_LABELS
        )
        fails = CounterMetricFamily(
            "locust_failures_total", "Total failed requests", labels=_LABELS
        )
        p50 = GaugeMetricFamily(
            "locust_response_time_p50_milliseconds", "p50 response time", labels=_LABELS
        )
        p95 = GaugeMetricFamily(
            "locust_response_time_p95_milliseconds", "p95 response time", labels=_LABELS
        )
        rps = GaugeMetricFamily(
            "locust_current_rps", "Current requests per second", labels=_LABELS
        )
        for entry in runner.stats.entries.values():
            labels = [entry.name, entry.method or ""]
            reqs.add_metric(labels, entry.num_requests)
            fails.add_metric(labels, entry.num_failures)
            p50.add_metric(labels, _percentile(entry, 0.5))
            p95.add_metric(labels, _percentile(entry, 0.95))
            rps.add_metric(labels, entry.current_rps or 0)
        yield reqs
        yield fails
        yield p50
        yield p95
        yield rps
