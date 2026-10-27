"""Assess one Locust plateau against explicit latency and failure targets."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import TypedDict


class PlateauAssessment(TypedDict):
    scenario: str
    finished: int
    failures: int
    failure_ratio: float
    p50_s: float
    p95_s: float
    turns_per_minute: float
    enough_samples: bool
    passed: bool


def assess(
    row: dict[str, str],
    p95_seconds: float,
    max_failure_ratio: float,
    minimum_turns: int,
) -> PlateauAssessment:
    finished, failures = int(row["Request Count"]), int(row["Failure Count"])
    p95 = float(row["95%"]) / 1000
    ratio = failures / finished if finished else 0.0
    enough = finished >= minimum_turns
    return {
        "scenario": row["Name"],
        "finished": finished,
        "failures": failures,
        "failure_ratio": ratio,
        "p50_s": float(row["50%"]) / 1000,
        "p95_s": p95,
        "turns_per_minute": float(row["Requests/s"]) * 60,
        "enough_samples": enough,
        "passed": enough and p95 <= p95_seconds and ratio <= max_failure_ratio,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stats_csv", type=Path)
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--think-seconds", type=float, required=True)
    parser.add_argument("--p95-seconds", type=float, required=True)
    parser.add_argument("--max-failure-ratio", type=float, default=0.01)
    parser.add_argument("--minimum-turns", type=int, default=100)
    args = parser.parse_args()
    if (
        args.users < 1
        or args.think_seconds < 0
        or args.p95_seconds <= 0
        or not 0 <= args.max_failure_ratio <= 1
        or args.minimum_turns < 1
    ):
        parser.error("Invalid user count, pacing, or acceptance thresholds")
    with args.stats_csv.open() as handle:
        rows = [
            assess(row, args.p95_seconds, args.max_failure_ratio, args.minimum_turns)
            for row in csv.DictReader(handle)
            if row["Name"].endswith(":total_turn")
        ]
    if not rows:
        parser.error("No total_turn rows; use the plateau's Locust stats CSV")
    print(
        json.dumps(
            {
                "users": args.users,
                "mean_think_seconds": args.think_seconds,
                "p95_target_s": args.p95_seconds,
                "maximum_failure_ratio": args.max_failure_ratio,
                "minimum_turns": args.minimum_turns,
                "results": rows,
                "passed": all(row["passed"] for row in rows),
                "scope": "One plateau, not a maximum capacity estimate. Exclude warmup and measure infrastructure separately.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
