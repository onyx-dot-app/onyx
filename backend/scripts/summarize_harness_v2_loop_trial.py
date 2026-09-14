"""Summarize paired v2 loop-speed arms after official fixed-gold grading."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from scripts.summarize_harness_v2_eval import (
    aggregate_scores,
    event_duration_sum,
    expected_doc_ids,
    index_unique_rows,
    is_number,
    latency_stats,
    read_jsonl,
    v2_stage_metrics,
)
from scripts.summarize_harness_v2_speed_trial import summarize as speed_summarize

ARMS = ("control", "optimized")
BOOTSTRAP_REPLICATES = 5000
BOOTSTRAP_SEED = 20260909
NOTABLE_REGRESSION_POINTS = 10.0


def finite_duration(value: Any) -> float | None:
    if not is_number(value):
        return None
    duration = float(value)
    return duration if math.isfinite(duration) else None


def result_events(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("raw")
    if not isinstance(raw, dict):
        return []
    result = raw.get("result")
    if not isinstance(result, dict):
        return []
    return [event for event in result.get("events", []) if isinstance(event, dict)]


def event_duration_values(
    events: list[dict[str, Any]], kind: str
) -> list[float] | None:
    values: list[float] = []
    for event in events:
        if event.get("kind") != kind:
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        duration = finite_duration(data.get("duration_ms"))
        if duration is None:
            return None
        values.append(duration)
    return values


def first_event_duration(events: list[dict[str, Any]], kind: str) -> float | None:
    values = event_duration_values(events, kind)
    if not values:
        return None
    return values[0]


def context_preparation_ms(events: list[dict[str, Any]]) -> float | None:
    return event_duration_sum(events, "context_preparation")


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def by_question_type(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    typed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        typed[str(row.get("question_type") or "unknown")].append(row)
    return dict(typed)


def paired_diffs(
    rows: list[dict[str, Any]], control_key: str, optimized_key: str
) -> list[float]:
    diffs: list[float] = []
    for row in rows:
        control_value = row.get(control_key)
        optimized_value = row.get(optimized_key)
        if control_value is None or optimized_value is None:
            continue
        diffs.append(float(optimized_value) - float(control_value))
    return diffs


def paired_mean_diff(rows: list[dict[str, Any]], metric: str) -> float | None:
    diffs = paired_diffs(rows, f"control_{metric}", f"optimized_{metric}")
    return mean(diffs)


def paired_median_diff(rows: list[dict[str, Any]], metric: str) -> float | None:
    diffs = paired_diffs(rows, f"control_{metric}", f"optimized_{metric}")
    return statistics.median(diffs) if diffs else None


def marginal_median_diff(rows: list[dict[str, Any]], metric: str) -> float | None:
    control_values: list[float] = []
    optimized_values: list[float] = []
    for row in rows:
        control_value = row.get(f"control_{metric}")
        optimized_value = row.get(f"optimized_{metric}")
        if control_value is None or optimized_value is None:
            continue
        control_values.append(float(control_value))
        optimized_values.append(float(optimized_value))
    if not control_values:
        return None
    return statistics.median(optimized_values) - statistics.median(control_values)


def paired_sample_count(rows: list[dict[str, Any]], metric: str) -> int:
    return len(paired_diffs(rows, f"control_{metric}", f"optimized_{metric}"))


def sample_question_types(
    rows_by_type: dict[str, list[dict[str, Any]]], rng: random.Random
) -> list[dict[str, Any]]:
    sampled: list[dict[str, Any]] = []
    for question_type in sorted(rows_by_type):
        bucket = rows_by_type[question_type]
        sampled.extend(rng.choice(bucket) for _ in bucket)
    return sampled


def confidence_interval(values: list[float]) -> dict[str, float | int | None | str]:
    return {
        "replicates": len(values),
        "low": None if not values else sorted(values)[int(0.025 * (len(values) - 1))],
        "high": None if not values else sorted(values)[int(0.975 * (len(values) - 1))],
        "method": (
            "paired nonparametric bootstrap, stratified by question_type, "
            f"seed={BOOTSTRAP_SEED}"
        ),
    }


def bootstrap_intervals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rng = random.Random(BOOTSTRAP_SEED)
    rows_by_type = by_question_type(rows)
    mean_non_search: list[float] = []
    median_paired_non_search_delta: list[float] = []
    marginal_median_non_search_delta: list[float] = []
    mean_quality: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = sample_question_types(rows_by_type, rng)
        mean_value = paired_mean_diff(sample, "non_search_loop_ms")
        paired_median_value = paired_median_diff(sample, "non_search_loop_ms")
        marginal_median_value = marginal_median_diff(sample, "non_search_loop_ms")
        quality_value = paired_mean_diff(sample, "combined_pct")
        if mean_value is not None:
            mean_non_search.append(mean_value)
        if paired_median_value is not None:
            median_paired_non_search_delta.append(paired_median_value)
        if marginal_median_value is not None:
            marginal_median_non_search_delta.append(marginal_median_value)
        if quality_value is not None:
            mean_quality.append(quality_value)
    return {
        "difference_direction": "optimized_minus_control",
        "valid_paired_sample_counts": {
            "non_search_loop_ms": paired_sample_count(rows, "non_search_loop_ms"),
            "combined_quality_pct": paired_sample_count(rows, "combined_pct"),
        },
        "mean_non_search_loop_ms": confidence_interval(mean_non_search),
        "median_paired_non_search_delta_ms": confidence_interval(
            median_paired_non_search_delta
        ),
        "median_non_search_loop_ms_difference_of_marginal_medians": confidence_interval(
            marginal_median_non_search_delta
        ),
        "mean_combined_quality_pct": confidence_interval(mean_quality),
    }


def per_type_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for question_type, typed_rows in sorted(by_question_type(rows).items()):
        output[question_type] = {
            arm: aggregate_scores([row[f"{arm}_score"] for row in typed_rows])
            for arm in ARMS
        }
        output[question_type]["mean_combined_delta_optimized_minus_control"] = mean(
            [
                float(row["optimized_combined_pct"])
                - float(row["control_combined_pct"])
                for row in typed_rows
            ]
        )
    return output


def quality_regressions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regressions = []
    for row in rows:
        delta = float(row["optimized_combined_pct"]) - float(
            row["control_combined_pct"]
        )
        if delta >= 0:
            continue
        regressions.append(
            {
                "question_id": row["question_id"],
                "question_type": row.get("question_type"),
                "combined_delta_optimized_minus_control": delta,
                "notable_10pt_or_more": delta <= -NOTABLE_REGRESSION_POINTS,
                "control_score": row["control_score"],
                "optimized_score": row["optimized_score"],
                "control_outcome": row["control_outcome"],
                "optimized_outcome": row["optimized_outcome"],
            }
        )
    return sorted(
        regressions,
        key=lambda item: item["combined_delta_optimized_minus_control"],
    )


def summarize(run: Path) -> dict[str, Any]:
    raw_summary = speed_summarize(run)
    manifest = raw_summary["manifest"]
    question_ids = manifest["question_ids"]
    questions = index_unique_rows(
        read_jsonl(run / "reference" / "selected_questions.jsonl"),
        "question_id",
        "reference questions",
    )
    per_question: list[dict[str, Any]] = []
    arm_rows = {
        arm: index_unique_rows(
            read_jsonl(run / f"results_{arm}.jsonl"), "question_id", arm
        )
        for arm in ARMS
    }
    for question_id in question_ids:
        row: dict[str, Any] = {
            "question_id": question_id,
            "question_type": questions[question_id].get("question_type"),
            "expected_doc_ids": expected_doc_ids(questions[question_id]),
        }
        for arm in ARMS:
            arm_summary = raw_summary["per_question"][question_id][arm]
            events = result_events(arm_rows[arm][question_id])
            stage = v2_stage_metrics(arm_rows[arm][question_id])
            row[f"{arm}_score"] = arm_summary["score"]
            row[f"{arm}_combined_pct"] = arm_summary["score"]["combined_pct"]
            row[f"{arm}_outcome"] = arm_summary["outcome"]
            row[f"{arm}_initial_decision_ms"] = first_event_duration(
                events, "model_decision"
            )
            row[f"{arm}_context_preparation_ms"] = context_preparation_ms(events)
            row[f"{arm}_non_search_loop_ms"] = stage["non_search_loop_ms"]
        row["combined_delta_optimized_minus_control"] = float(
            row["optimized_combined_pct"]
        ) - float(row["control_combined_pct"])
        if (
            row["control_non_search_loop_ms"] is not None
            and row["optimized_non_search_loop_ms"] is not None
        ):
            row["non_search_loop_delta_ms_optimized_minus_control"] = float(
                row["optimized_non_search_loop_ms"]
            ) - float(row["control_non_search_loop_ms"])
        else:
            row["non_search_loop_delta_ms_optimized_minus_control"] = None
        per_question.append(row)

    arm_extra: dict[str, Any] = {}
    for arm in ARMS:
        arm_extra[arm] = {
            "scores_by_type": {
                question_type: values[arm]
                for question_type, values in per_type_scores(per_question).items()
            },
            "initial_decision_ms": latency_stats(
                [
                    float(row[f"{arm}_initial_decision_ms"])
                    for row in per_question
                    if row[f"{arm}_initial_decision_ms"] is not None
                ]
            ),
            "context_preparation_ms": latency_stats(
                [
                    float(row[f"{arm}_context_preparation_ms"])
                    for row in per_question
                    if row[f"{arm}_context_preparation_ms"] is not None
                ]
            ),
        }

    return {
        "comparison_scope": (
            "Paired v2 loop trial summary. Use intervals as descriptive evidence; "
            "do not infer statistical parity or leaderboard movement from this file alone."
        ),
        "question_count": len(question_ids),
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "raw_summary": raw_summary,
        "arms": arm_extra,
        "per_type": per_type_scores(per_question),
        "bootstrap_95ci": bootstrap_intervals(per_question),
        "quality_regressions": quality_regressions(per_question),
        "raw_rows": {
            arm: [arm_rows[arm][question_id] for question_id in question_ids]
            for arm in ARMS
        },
        "per_question": per_question,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    summary = summarize(args.run_dir)
    with args.output.open("x") as stream:
        stream.write(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
