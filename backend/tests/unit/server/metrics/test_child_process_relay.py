"""The relay of a spawned process's metrics to its worker. Each side has its
own registry here, as the two processes have in production."""

import os
import subprocess
import sys
from pathlib import Path

from prometheus_client import CollectorRegistry, Counter, Gauge

from onyx.server.metrics.child_process_relay import (
    STALE_SECONDS,
    GaugeMerge,
    RelayReader,
    RelayWriter,
)


class _Side:
    def __init__(self) -> None:
        registry = CollectorRegistry()
        self.requests = Counter(
            "relay_test_requests_total", "", ["outcome"], registry=registry
        )
        self.in_flight = Gauge("relay_test_in_flight", "", ["pool"], registry=registry)
        self.budget = Gauge("relay_test_budget", "", ["scope"], registry=registry)
        self.registry = registry

    def gauges(self) -> list[tuple[Gauge, GaugeMerge]]:
        return [(self.in_flight, GaugeMerge.SUM), (self.budget, GaugeMerge.MIN)]

    def value(self, name: str, labels: dict[str, str]) -> float | None:
        return self.registry.get_sample_value(name, labels)


def _write_as(
    directory: Path, pid: int, side: _Side, final: bool = False
) -> RelayWriter:
    writer = RelayWriter(directory, [side.requests], side.gauges())
    writer._path = directory / f"{pid}.json"
    writer.write(final=final)
    return writer


def test_counters_add_up_and_stay_after_the_process_ends(tmp_path: Path) -> None:
    worker = _Side()
    reader = RelayReader(tmp_path, [worker.requests], worker.gauges())
    first, second = _Side(), _Side()

    first.requests.labels(outcome="ok").inc(3)
    second.requests.labels(outcome="ok").inc(2)
    second.requests.labels(outcome="rate_limited").inc()
    _write_as(tmp_path, 1, first)
    _write_as(tmp_path, 2, second)
    reader.merge_once()
    assert worker.value("relay_test_requests_total", {"outcome": "ok"}) == 5

    # Only what a process counted since its last snapshot is added.
    first.requests.labels(outcome="ok").inc(4)
    _write_as(tmp_path, 1, first, final=True)
    reader.merge_once()
    reader.merge_once()
    assert worker.value("relay_test_requests_total", {"outcome": "ok"}) == 9
    assert worker.value("relay_test_requests_total", {"outcome": "rate_limited"}) == 1
    assert not (tmp_path / "1.json").exists()


def test_gauges_merge_over_the_running_processes(tmp_path: Path) -> None:
    worker = _Side()
    reader = RelayReader(tmp_path, [worker.requests], worker.gauges())
    first, second = _Side(), _Side()

    first.in_flight.labels(pool="listing").set(10)
    first.budget.labels(scope="project").set(800)
    second.in_flight.labels(pool="listing").set(6)
    second.budget.labels(scope="project").set(400)
    _write_as(tmp_path, 1, first)
    _write_as(tmp_path, 2, second, final=True)
    reader.merge_once()
    # The final snapshot of the second process does not count as running.
    assert worker.value("relay_test_in_flight", {"pool": "listing"}) == 10
    assert worker.value("relay_test_budget", {"scope": "project"}) == 800

    second_again = _Side()
    second_again.in_flight.labels(pool="listing").set(6)
    second_again.budget.labels(scope="project").set(400)
    _write_as(tmp_path, 3, second_again)
    reader.merge_once()
    assert worker.value("relay_test_in_flight", {"pool": "listing"}) == 16
    assert worker.value("relay_test_budget", {"scope": "project"}) == 400


def _ended_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def _make_stale(path: Path) -> None:
    old = path.stat().st_mtime - STALE_SECONDS - 1
    os.utime(path, (old, old))


def test_a_process_that_stopped_writing_is_dropped(tmp_path: Path) -> None:
    worker = _Side()
    reader = RelayReader(tmp_path, [worker.requests], worker.gauges())
    child = _Side()
    child.requests.labels(outcome="ok").inc(7)
    child.in_flight.labels(pool="listing").set(4)
    pid = _ended_pid()
    _write_as(tmp_path, pid, child)
    reader.merge_once()
    assert worker.value("relay_test_in_flight", {"pool": "listing"}) == 4

    # Killed with no last snapshot.
    _make_stale(tmp_path / f"{pid}.json")
    reader.merge_once()

    assert worker.value("relay_test_requests_total", {"outcome": "ok"}) == 7
    assert worker.value("relay_test_in_flight", {"pool": "listing"}) is None
    assert not (tmp_path / f"{pid}.json").exists()


def test_a_new_process_with_a_reused_pid_counts_from_zero(tmp_path: Path) -> None:
    """Two processes with one PID: the reader must not read the second
    snapshot as the first process's."""
    worker = _Side()
    reader = RelayReader(tmp_path, [worker.requests], worker.gauges())
    first, second = _Side(), _Side()

    first.requests.labels(outcome="ok").inc(100)
    RelayWriter(tmp_path, [first.requests], first.gauges()).write(final=False)
    reader.merge_once()
    second.requests.labels(outcome="ok").inc(10)
    RelayWriter(tmp_path, [second.requests], second.gauges()).write(final=False)
    reader.merge_once()

    assert worker.value("relay_test_requests_total", {"outcome": "ok"}) == 110


def test_a_running_process_keeps_its_watermark_when_its_writes_stall(
    tmp_path: Path,
) -> None:
    """A process that runs but could not write for a while loses its gauges.
    Its next snapshot adds only what it counted since the last one."""
    worker = _Side()
    reader = RelayReader(tmp_path, [worker.requests], worker.gauges())
    child = _Side()
    writer = RelayWriter(tmp_path, [child.requests], child.gauges())
    child.requests.labels(outcome="ok").inc(100)
    child.in_flight.labels(pool="listing").set(4)
    writer.write(final=False)
    reader.merge_once()

    (snapshot,) = tmp_path.glob("*.json")
    _make_stale(snapshot)
    reader.merge_once()
    assert worker.value("relay_test_in_flight", {"pool": "listing"}) is None

    child.requests.labels(outcome="ok").inc(10)
    writer.write(final=False)
    reader.merge_once()

    assert worker.value("relay_test_requests_total", {"outcome": "ok"}) == 110
    assert worker.value("relay_test_in_flight", {"pool": "listing"}) == 4
