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


METRIC_NAMES = tuple(field.name for field in fields(Counts))

local: dict[str, Counts] = {}
workers: dict[str, dict[str, dict[str, int]]] = {}
next_user = 0


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
