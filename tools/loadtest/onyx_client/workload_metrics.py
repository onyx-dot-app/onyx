"""Per-worker workload counts; snapshots replace prior worker reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields


@dataclass
class Counts:
    active: int = 0
    started: int = 0
    finished: int = 0
    answer_chars: int = 0
    packets: int = 0
    search_calls: int = 0
    reasoning_packets: int = 0
    citations: int = 0
    code_programs: int = 0
    code_waits: int = 0
    nested_search_calls: int = 0
    code_failures: int = 0
    code_planned_failures: int = 0
    code_output_chars: int = 0


METRIC_NAMES = tuple(field.name for field in fields(Counts))
# Counts that a turn's stream summary (onyx_client/stream_parser.py) adds.
STREAM_COUNTS = tuple(
    name for name in METRIC_NAMES if name not in ("active", "started", "finished")
)

local: dict[str, Counts] = {}
workers: dict[str, dict[str, dict[str, int]]] = {}
next_user = 0

# Session turn ranges that per-turn-index latency is reported in; ranges keep
# the number of metric names small.
TURN_RANGES = ((1, 1), (2, 5), (6, 10), (11, 20), (21, 40), (41, 80))


def turn_range(turn: int) -> str:
    """The range label of a 1-based session turn: "1", "2-5", ..., "81+"."""
    for low, high in TURN_RANGES:
        if low <= turn <= high:
            return str(low) if low == high else f"{low}-{high}"
    return f"{TURN_RANGES[-1][1] + 1}+"


def reset() -> None:
    global next_user
    local.clear()
    workers.clear()
    next_user = 0


def allocate_user() -> int:
    global next_user
    index = next_user
    next_user += 1
    return index


def snapshot() -> dict[str, dict[str, int]]:
    return {name: asdict(counts) for name, counts in local.items()}


def aggregate(active_workers: set[str] | None = None) -> dict[str, dict[str, int]]:
    total: dict[str, dict[str, int]] = {}
    reports = workers.items() if workers else [("local", snapshot())]
    for worker, report in reports:
        for scenario, values in report.items():
            row = total.setdefault(scenario, {})
            for key, value in values.items():
                if (
                    key == "active"
                    and active_workers is not None
                    and worker not in active_workers
                ):
                    value = 0
                row[key] = row.get(key, 0) + value
    return total
