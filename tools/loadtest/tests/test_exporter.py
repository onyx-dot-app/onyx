"""Tests for the Locust Prometheus collector.

Uses lightweight fakes for the runner/stats so it imports neither locust nor
gevent — keeping it safe to run in the same pytest session as the fastapi
mock_llm tests.
"""

from __future__ import annotations

from typing import Any

from prometheus_collector import LocustCollector


class _Entry:
    def __init__(
        self, name: str, method: str, num_requests: int, num_failures: int, p95: float
    ) -> None:
        self.name = name
        self.method = method
        self.num_requests = num_requests
        self.num_failures = num_failures
        self.current_rps = 0.0
        self._p95 = p95

    def get_current_response_time_percentile(self, _pct: float) -> float | None:
        return None  # cache empty → collector falls back to all-time

    def get_response_time_percentile(self, pct: float) -> float:
        return self._p95 if pct >= 0.95 else self._p95 / 2


class _Stats:
    def __init__(self, entries: dict[tuple[str, str], _Entry]) -> None:
        self.entries = entries


class _Runner:
    def __init__(self, stats: _Stats, user_count: int) -> None:
        self.stats = stats
        self.user_count = user_count


class _Env:
    def __init__(self, runner: Any) -> None:
        self.runner = runner


def _collect(collector: LocustCollector) -> dict[str, Any]:
    return {mf.name: mf for mf in collector.collect()}


def test_collector_emits_locust_metrics() -> None:
    entries = {
        ("chat:total_turn", "CHAT"): _Entry("chat:total_turn", "CHAT", 2, 1, 1200),
        ("search:first_search_doc", "CHAT"): _Entry(
            "search:first_search_doc", "CHAT", 1, 0, 300
        ),
    }
    families = _collect(LocustCollector(_Env(_Runner(_Stats(entries), user_count=42))))

    # prometheus_client strips the _total suffix from the family name.
    assert families["locust_users"].samples[0].value == 42

    reqs = {s.labels["name"]: s.value for s in families["locust_requests"].samples}
    assert reqs["chat:total_turn"] == 2
    assert reqs["search:first_search_doc"] == 1

    fails = {s.labels["name"]: s.value for s in families["locust_failures"].samples}
    assert fails["chat:total_turn"] == 1

    p95 = {
        s.labels["name"]: s.value
        for s in families["locust_response_time_p95_milliseconds"].samples
    }
    assert p95["chat:total_turn"] > 0


def test_collector_no_runner_is_empty() -> None:
    families = _collect(LocustCollector(_Env(None)))
    assert families == {}
