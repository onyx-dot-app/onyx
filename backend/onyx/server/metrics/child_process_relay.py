"""Relays the source-API, adaptive-pool and listing-pause metrics of a spawned indexing
process to the worker that spawned it.

A docfetching worker runs each connector in a spawned process
(``SimpleJobClient``). The spawned process has its own metric objects, and no
scraper can reach it. So the spawned process writes a snapshot of the relayed
metrics to a file in a directory of the worker, at an interval and when it
ends. The worker reads the files and adds them to its own metric objects,
which its metrics server serves.

- Counters: the worker adds what each process counted since its last
  snapshot, so a total does not go down when a process ends.
- Gauges: the worker sets each series from the processes that run now. Pool
  gauges are the sum. Limiter gauges are the lowest or highest value: the
  budget is shared, and processes differ only in how recently they read it.
"""

import json
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Gauge

from onyx.server.metrics.adaptive_pool_metrics import (
    ADAPTIVE_POOL_CUTS,
    ADAPTIVE_POOL_GROWS,
    ADAPTIVE_POOL_IN_FLIGHT,
    ADAPTIVE_POOL_LIMIT,
)
from onyx.server.metrics.listing_backpressure_metrics import (
    LISTING_BACKPRESSURE_PAUSED_SECONDS,
    LISTING_BACKPRESSURE_PAUSES,
)
from onyx.server.metrics.source_api_metrics import (
    LIMITER_BUDGET,
    LIMITER_CUT_USERS,
    LIMITER_CUTS,
    LIMITER_LOCAL_WAITERS,
    LIMITER_PAUSED_SECONDS,
    LIMITER_PAUSES,
    LIMITER_REDIS_WAITERS,
    LIMITER_UNITS,
    LIMITER_WAIT_SECONDS,
    SOURCE_API_REQUESTS,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# The worker sets this for the processes it spawns.
RELAY_DIR_ENV = "ONYX_CHILD_METRICS_RELAY_DIR"
RELAY_INTERVAL_SECONDS = 5.0
# The gauges of a process that wrote no snapshot for this long no longer
# count. Its counter watermark stays until the process has ended.
STALE_SECONDS = 60.0


class GaugeMerge(str, Enum):
    SUM = "sum"
    MIN = "min"
    MAX = "max"


RELAYED_COUNTERS: tuple[Counter, ...] = (
    SOURCE_API_REQUESTS,
    LIMITER_CUTS,
    LIMITER_WAIT_SECONDS,
    LIMITER_UNITS,
    LIMITER_PAUSES,
    LIMITER_PAUSED_SECONDS,
    ADAPTIVE_POOL_CUTS,
    ADAPTIVE_POOL_GROWS,
    LISTING_BACKPRESSURE_PAUSES,
    LISTING_BACKPRESSURE_PAUSED_SECONDS,
)
RELAYED_GAUGES: tuple[tuple[Gauge, GaugeMerge], ...] = (
    (LIMITER_BUDGET, GaugeMerge.MIN),
    (LIMITER_CUT_USERS, GaugeMerge.MAX),
    (LIMITER_LOCAL_WAITERS, GaugeMerge.SUM),
    (LIMITER_REDIS_WAITERS, GaugeMerge.MAX),
    (ADAPTIVE_POOL_LIMIT, GaugeMerge.SUM),
    (ADAPTIVE_POOL_IN_FLIGHT, GaugeMerge.SUM),
)

# One series: its label names and values, in the order of the metric's labels.
_Labels = dict[str, str]
_Samples = list[tuple[_Labels, float]]


def _family_name(metric: Counter | Gauge) -> str:
    return next(iter(metric.collect())).name


def _samples(metric: Counter | Gauge) -> _Samples:
    samples: _Samples = []
    for family in metric.collect():
        for sample in family.samples:
            # A counter also has a _created sample.
            if isinstance(metric, Counter) and not sample.name.endswith("_total"):
                continue
            samples.append((dict(sample.labels), sample.value))
    return samples


def _merge(values: list[float], merge: GaugeMerge) -> float:
    if merge == GaugeMerge.SUM:
        return sum(values)
    if merge == GaugeMerge.MIN:
        return min(values)
    return max(values)


def _series_key(labels: _Labels) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(labels.items()))


def _snapshot_name(pid: int) -> str:
    # The id keeps a new process with a reused PID apart from the snapshot
    # and the watermark of the old one.
    return f"{pid}-{uuid.uuid4().hex}.json"


def _writer_has_ended(file_name: str) -> bool:
    """True when the process that writes the snapshot no longer runs."""
    try:
        pid = int(file_name.split("-", 1)[0].removesuffix(".json"))
    except ValueError:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # The process exists, and it belongs to another user.
        return False
    return False


class RelayWriter:
    """Writes the snapshot of a spawned process."""

    def __init__(
        self,
        directory: Path,
        counters: Sequence[Counter] = RELAYED_COUNTERS,
        gauges: Sequence[tuple[Gauge, GaugeMerge]] = RELAYED_GAUGES,
    ) -> None:
        self._path = directory / _snapshot_name(os.getpid())
        self._counters = counters
        self._gauges = [gauge for gauge, _ in gauges]
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def write(self, final: bool) -> None:
        snapshot: dict[str, Any] = {
            "final": final,
            "counters": {_family_name(c): _samples(c) for c in self._counters},
            "gauges": {_family_name(g): _samples(g) for g in self._gauges},
        }
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot))
        os.replace(temporary, self._path)

    def _run(self) -> None:
        while not self._stop.wait(RELAY_INTERVAL_SECONDS):
            try:
                self.write(final=False)
            except OSError:
                logger.debug("Could not write the metrics snapshot", exc_info=True)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="metrics-relay-writer"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=RELAY_INTERVAL_SECONDS)
        try:
            self.write(final=True)
        except OSError:
            logger.debug("Could not write the last metrics snapshot", exc_info=True)


class RelayReader:
    """Adds the snapshots of spawned processes to this process's metrics."""

    def __init__(
        self,
        directory: Path,
        counters: Sequence[Counter] = RELAYED_COUNTERS,
        gauges: Sequence[tuple[Gauge, GaugeMerge]] = RELAYED_GAUGES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._directory = directory
        self._counters = {_family_name(c): c for c in counters}
        self._gauges = {_family_name(g): (g, merge) for g, merge in gauges}
        self._clock = clock
        # Snapshot file -> (family, series) -> the count already added.
        self._added: dict[str, dict[tuple[str, tuple], float]] = {}
        # Snapshot file -> family -> samples, for the processes that run now.
        self._live_gauges: dict[str, dict[str, _Samples]] = {}
        # Family -> the series that this reader set.
        self._published: dict[str, dict[tuple, _Labels]] = {}
        self._stop = threading.Event()

    def _add_counters(self, file: str, counters: dict[str, Any]) -> None:
        added = self._added.setdefault(file, {})
        for family, samples in counters.items():
            counter = self._counters.get(family)
            if counter is None:
                continue
            for labels, value in samples:
                key = (family, _series_key(labels))
                delta = float(value) - added.get(key, 0.0)
                if delta > 0:
                    counter.labels(**labels).inc(delta)
                    added[key] = float(value)

    def _publish_gauges(self) -> None:
        for family, (gauge, merge) in self._gauges.items():
            values: dict[tuple, list[float]] = {}
            labels_of: dict[tuple, _Labels] = {}
            for gauges in self._live_gauges.values():
                for labels, value in gauges.get(family, []):
                    key = _series_key(labels)
                    values.setdefault(key, []).append(float(value))
                    labels_of[key] = labels
            for key, series_values in values.items():
                gauge.labels(**labels_of[key]).set(_merge(series_values, merge))
            published = self._published.setdefault(family, {})
            for key, labels in list(published.items()):
                if key not in values:
                    try:
                        gauge.remove(*labels.values())
                    except KeyError:
                        pass
                    del published[key]
            published.update(labels_of)

    def merge_once(self) -> None:
        now = self._clock()
        for path in self._directory.glob("*.json"):
            try:
                snapshot = json.loads(path.read_text())
                modified = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            self._add_counters(path.name, snapshot.get("counters", {}))
            if snapshot.get("final") or (
                now - modified > STALE_SECONDS and _writer_has_ended(path.name)
            ):
                self._added.pop(path.name, None)
                self._live_gauges.pop(path.name, None)
                path.unlink(missing_ok=True)
            elif now - modified > STALE_SECONDS:
                # The process runs but could not write: its gauges are old.
                # Its next snapshot still counts from the watermark.
                self._live_gauges.pop(path.name, None)
            else:
                self._live_gauges[path.name] = snapshot.get("gauges", {})
        self._publish_gauges()

    def _run(self) -> None:
        while not self._stop.wait(RELAY_INTERVAL_SECONDS):
            try:
                self.merge_once()
            except Exception:
                logger.exception("Could not read the metrics of spawned processes")

    def start(self) -> None:
        threading.Thread(
            target=self._run, daemon=True, name="metrics-relay-reader"
        ).start()


_writer: RelayWriter | None = None


def start_relay_writer() -> None:
    """For a spawned process. Does nothing when the worker set no directory."""
    global _writer
    directory = os.environ.get(RELAY_DIR_ENV)
    if not directory or _writer is not None:
        return
    _writer = RelayWriter(Path(directory))
    _writer.start()


def stop_relay_writer() -> None:
    """Writes the last snapshot of a spawned process."""
    global _writer
    if _writer is not None:
        _writer.stop()
        _writer = None


def start_relay_reader() -> None:
    """For a worker that spawns processes. Call it before the first spawn:
    a process gets the directory from its environment."""
    directory = tempfile.mkdtemp(prefix="onyx-metrics-relay-")
    os.environ[RELAY_DIR_ENV] = directory
    RelayReader(Path(directory)).start()
    logger.info("Relaying the metrics of spawned processes through %s", directory)
