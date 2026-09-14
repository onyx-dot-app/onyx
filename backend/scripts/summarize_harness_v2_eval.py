"""Summarize a frozen harness v2 evaluation after official grading."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

VARIANTS = ("legacy", "v2")
OFFICIAL_RESULTS_FILE = "official_results_repeat_01.json"


def empty_v2_stage_metrics() -> dict[str, float | None]:
    return {
        "setup_ms": None,
        "outer_model_decision_ms": None,
        "non_search_loop_ms": None,
        "internal_search_tool_ms": None,
        "internal_search_retrieval_ms": None,
        "internal_search_answer_synthesis_ms": None,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def finite_number(value: Any, label: str) -> float:
    if not is_number(value):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def percentage(value: Any, label: str) -> float:
    number = finite_number(value, label)
    if number < 0 or number > 100:
        raise ValueError(f"{label} must be between 0 and 100")
    return number


def nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def index_unique_rows(
    rows: list[dict[str, Any]], key: str, label: str
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        value = str(row[key])
        if value in indexed:
            duplicates.append(value)
        indexed[value] = row
    if duplicates:
        raise ValueError(f"Duplicate {label}: {sorted(set(duplicates))}")
    return indexed


def require_question_sets(
    grade_dir: Path,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    selected_by_variant = {
        variant: index_unique_rows(
            read_jsonl(grade_dir / variant / "selected_questions.jsonl"),
            "question_id",
            f"{variant} selected question IDs",
        )
        for variant in VARIANTS
    }
    legacy_ids = set(selected_by_variant["legacy"])
    v2_ids = set(selected_by_variant["v2"])
    if not legacy_ids:
        raise ValueError("Selected question set cannot be empty")
    if legacy_ids != v2_ids:
        raise ValueError(
            "Selected question sets differ between variants: "
            f"legacy_only={sorted(legacy_ids - v2_ids)} "
            f"v2_only={sorted(v2_ids - legacy_ids)}"
        )
    mismatched_ids = [
        question_id
        for question_id in sorted(legacy_ids)
        if selected_by_variant["legacy"][question_id]
        != selected_by_variant["v2"][question_id]
    ]
    if mismatched_ids:
        raise ValueError(
            f"Selected question records differ between variants: {mismatched_ids}"
        )
    return sorted(legacy_ids), selected_by_variant["legacy"]


def require_variant_rows(
    rows: list[dict[str, Any]], question_ids: list[str], variant: str, label: str
) -> dict[str, dict[str, Any]]:
    expected_ids = set(question_ids)
    selected = [row for row in rows if row.get("variant") == variant]
    indexed = index_unique_rows(selected, "question_id", f"{label} {variant} IDs")
    actual_ids = set(indexed)
    if actual_ids != expected_ids:
        raise ValueError(
            f"Expected exactly one {label} row per question for {variant}: "
            f"missing={sorted(expected_ids - actual_ids)} "
            f"unexpected={sorted(actual_ids - expected_ids)}"
        )
    return indexed


def require_sample_rows(
    grade_dir: Path, question_ids: list[str], variant: str
) -> dict[str, dict[str, Any]]:
    samples = read_jsonl(grade_dir / variant / "samples.jsonl")
    for row in samples:
        row.setdefault("variant", variant)
    return require_variant_rows(samples, question_ids, variant, "sample")


def require_official_results(
    grade_dir: Path,
    samples: dict[str, dict[str, Any]],
    variant: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payload = read_json_object(grade_dir / variant / OFFICIAL_RESULTS_FILE)
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError(f"Official results for {variant} must contain questions list")
    rows = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError(f"Official result row for {variant} must be an object")
        rows.append(question)
    indexed = index_unique_rows(rows, "question_id", f"official result {variant} IDs")
    succeeded_ids = {
        question_id
        for question_id, sample in samples.items()
        if sample["status"] == "succeeded"
    }
    actual_ids = set(indexed)
    if actual_ids != succeeded_ids:
        raise ValueError(
            f"Official scored IDs must equal succeeded sample IDs for {variant}: "
            f"missing={sorted(succeeded_ids - actual_ids)} "
            f"unexpected={sorted(actual_ids - succeeded_ids)}"
        )
    aggregate_stats = payload.get("aggregate_stats", {})
    if not isinstance(aggregate_stats, dict):
        raise ValueError(f"Official aggregate_stats for {variant} must be an object")
    return indexed, aggregate_stats


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * pct / 100
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return (
        sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction
    )


def latency_stats(values: list[float]) -> dict[str, float | int | None | str]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p99": percentile(values, 99),
        "max": max(values) if values else None,
        "percentile_method": "linear interpolation; small-sample descriptive only",
    }


def mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def score_sample(
    sample: dict[str, Any],
    official: dict[str, dict[str, Any]],
    expected_doc_ids: list[str],
) -> dict[str, Any]:
    if sample["status"] == "failed":
        has_expected_docs = bool(expected_doc_ids)
        return {
            "succeeded": False,
            "correctness_pct": 0.0,
            "answer_correct": False,
            "completeness_pct": 0.0,
            "combined_pct": 0.0,
            "document_recall_pct": 0.0 if has_expected_docs else None,
            "document_recall_applicable": has_expected_docs,
            "invalid_extra_docs": 0 if has_expected_docs else None,
            "invalid_extra_docs_applicable": has_expected_docs,
        }
    if sample["status"] != "succeeded":
        raise ValueError(f"Unexpected sample status: {sample['status']}")
    row = official[str(sample["question_id"])]
    answer_correct = row["answer_correct"]
    if not isinstance(answer_correct, bool):
        raise ValueError("answer_correct must be a boolean")
    completeness_pct = percentage(row["completeness_pct"], "completeness_pct")
    has_expected_docs = bool(expected_doc_ids)
    if has_expected_docs:
        document_recall_pct: float | None = percentage(
            row["document_recall_pct"], "document_recall_pct"
        )
        invalid_extra_docs: int | None = nonnegative_int(
            row.get("invalid_extra_docs", 0), "invalid_extra_docs"
        )
    else:
        if row.get("document_recall_pct") is not None:
            raise ValueError(
                "document_recall_pct must be null when expected_doc_ids is empty"
            )
        if row.get("invalid_extra_docs") is not None:
            raise ValueError(
                "invalid_extra_docs must be null when expected_doc_ids is empty"
            )
        document_recall_pct = None
        invalid_extra_docs = None
    return {
        "succeeded": True,
        "correctness_pct": 100.0 if answer_correct else 0.0,
        "answer_correct": answer_correct,
        "completeness_pct": completeness_pct,
        "combined_pct": completeness_pct if answer_correct else 0.0,
        "document_recall_pct": document_recall_pct,
        "document_recall_applicable": has_expected_docs,
        "invalid_extra_docs": invalid_extra_docs,
        "invalid_extra_docs_applicable": has_expected_docs,
    }


def expected_doc_ids(question: dict[str, Any]) -> list[str]:
    for key in ("expected_doc_ids", "gold_document_ids", "document_ids"):
        value = question.get(key)
        if isinstance(value, list):
            return [str(item) for item in value]
    return []


def event_duration_ms(
    event: dict[str, Any], kind: str, tool: str | None = None
) -> float:
    if event.get("kind") != kind:
        return 0.0
    data = event.get("data")
    if not isinstance(data, dict):
        return 0.0
    if tool is not None and data.get("tool") != tool:
        return 0.0
    duration = data.get("duration_ms")
    return float(duration) if is_number(duration) and math.isfinite(duration) else 0.0


def event_duration_sum(
    events: list[dict[str, Any]], kind: str, tool: str | None = None
) -> float | None:
    values: list[float] = []
    for event in events:
        if event.get("kind") != kind:
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        if tool is not None and data.get("tool") != tool:
            continue
        duration = data.get("duration_ms")
        if not is_number(duration):
            return None
        value = float(duration)
        if not math.isfinite(value):
            return None
        values.append(value)
    return sum(values) if values else None


def receipt_stage_sum(receipts: list[dict[str, Any]], field: str) -> float | None:
    values: list[float] = []
    for receipt in receipts:
        nested = receipt.get("tool_receipt")
        stage_receipt = nested if isinstance(nested, dict) else receipt
        tool_name = stage_receipt.get("tool_name") or receipt.get("tool_name")
        if tool_name != "internal_search":
            continue
        value = stage_receipt.get(field)
        if not isinstance(value, int | float) or isinstance(value, bool):
            return None
        stage_value = float(value)
        if not math.isfinite(stage_value):
            return None
        values.append(stage_value)
    return sum(values) if values else None


def v2_stage_metrics(raw_row: dict[str, Any] | None) -> dict[str, float | None]:
    if raw_row is None:
        return empty_v2_stage_metrics()
    raw_response = raw_row.get("raw")
    if not isinstance(raw_response, dict):
        return empty_v2_stage_metrics()
    result = raw_response.get("result")
    if not isinstance(result, dict):
        return empty_v2_stage_metrics()
    events = [event for event in result.get("events", []) if isinstance(event, dict)]
    receipts = [
        receipt for receipt in result.get("receipts", []) if isinstance(receipt, dict)
    ]
    has_unmeasured_internal_search_timeout = any(
        event.get("kind") == "tool_timeout"
        and isinstance(event.get("data"), dict)
        and event["data"].get("tool") == "internal_search"
        and not is_number(event["data"].get("duration_ms"))
        for event in events
    )
    search_ms = (
        None
        if has_unmeasured_internal_search_timeout
        else event_duration_sum(events, "tool_call", "internal_search")
    )
    total_ms = result.get("total_ms")
    non_search_ms = (
        float(total_ms) - search_ms
        if is_number(total_ms)
        and math.isfinite(total_ms)
        and search_ms is not None
        and total_ms >= search_ms
        else None
    )
    return {
        "setup_ms": float(raw_response["setup_ms"])
        if is_number(raw_response.get("setup_ms"))
        else None,
        "outer_model_decision_ms": event_duration_sum(events, "model_decision"),
        "non_search_loop_ms": non_search_ms,
        "internal_search_tool_ms": search_ms,
        "internal_search_retrieval_ms": receipt_stage_sum(receipts, "retrieval_ms"),
        "internal_search_answer_synthesis_ms": receipt_stage_sum(
            receipts, "answer_synthesis_ms"
        ),
    }


def v2_cost(raw_row: dict[str, Any]) -> tuple[float | None, int | None]:
    raw_response = raw_row.get("raw")
    if not isinstance(raw_response, dict):
        return None, None
    result = raw_response.get("result")
    if not isinstance(result, dict):
        return None, None
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return None, None
    cost = usage.get("cost_cents")
    unpriced_calls = usage.get("unpriced_calls")
    return (
        float(cost) if is_number(cost) and math.isfinite(float(cost)) else None,
        int(unpriced_calls)
        if isinstance(unpriced_calls, int) and not isinstance(unpriced_calls, bool)
        else None,
    )


def aggregate_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    recall_values = [
        float(row["document_recall_pct"])
        for row in rows
        if row["document_recall_applicable"]
    ]
    invalid_extra_doc_values = [
        float(row["invalid_extra_docs"])
        for row in rows
        if row["invalid_extra_docs_applicable"]
    ]
    return {
        "n": len(rows),
        "completion_rate_pct": 100
        * sum(1 for row in rows if row["succeeded"])
        / len(rows),
        "strict_correctness_pct_mean": mean(
            [float(row["correctness_pct"]) for row in rows]
        ),
        "completeness_pct_mean": mean([float(row["completeness_pct"]) for row in rows]),
        "combined_pct_mean": mean([float(row["combined_pct"]) for row in rows]),
        "document_recall_pct_mean_applicable": mean(recall_values),
        "document_recall_applicable_n": len(recall_values),
        "invalid_extra_docs_mean": mean(invalid_extra_doc_values),
        "invalid_extra_docs_applicable_n": len(invalid_extra_doc_values),
    }


def aggregate_stage_metrics(
    per_question: list[dict[str, float | None]],
) -> dict[str, dict[str, float | int | None | str]]:
    output = {}
    for key in (
        "setup_ms",
        "outer_model_decision_ms",
        "non_search_loop_ms",
        "internal_search_tool_ms",
        "internal_search_retrieval_ms",
        "internal_search_answer_synthesis_ms",
    ):
        values: list[float] = []
        for row in per_question:
            value = row[key]
            if value is not None:
                values.append(float(value))
        output[key] = latency_stats(values)
    return output


def unresolved_citation_summary(samples: dict[str, dict[str, Any]]) -> dict[str, Any]:
    question_ids = []
    total = 0
    for question_id, sample in samples.items():
        unresolved = sample.get("unresolved_citation_numbers")
        if not isinstance(unresolved, list) or not unresolved:
            continue
        question_ids.append(question_id)
        total += len(unresolved)
    return {"count": total, "question_ids": sorted(question_ids)}


def summarize(raw_results: Path, grade_dir: Path) -> dict[str, Any]:
    question_ids, questions = require_question_sets(grade_dir)
    raw_rows = read_jsonl(raw_results)
    raw_by_variant = {
        variant: require_variant_rows(raw_rows, question_ids, variant, "raw result")
        for variant in VARIANTS
    }
    samples_by_variant = {
        variant: require_sample_rows(grade_dir, question_ids, variant)
        for variant in VARIANTS
    }
    official_by_variant: dict[str, dict[str, dict[str, Any]]] = {}
    official_aggregates: dict[str, dict[str, Any]] = {}
    for variant in VARIANTS:
        official_by_variant[variant], official_aggregates[variant] = (
            require_official_results(grade_dir, samples_by_variant[variant], variant)
        )

    variant_scores: dict[str, list[dict[str, Any]]] = {
        variant: [] for variant in VARIANTS
    }
    per_question: list[dict[str, Any]] = []
    v2_stage_rows: list[dict[str, float | None]] = []
    v2_cost_values: list[float] = []
    v2_unpriced_values: list[int] = []
    for question_id in question_ids:
        question = questions[question_id]
        docs = expected_doc_ids(question)
        variants: dict[str, dict[str, Any]] = {}
        for variant in VARIANTS:
            sample = samples_by_variant[variant][question_id]
            scored = score_sample(sample, official_by_variant[variant], docs)
            variant_scores[variant].append(scored)
            variants[variant] = {
                "status": sample["status"],
                "harness_outcome": sample.get("harness_outcome"),
                **scored,
            }
        stages = v2_stage_metrics(raw_by_variant["v2"].get(question_id))
        v2_stage_rows.append(stages)
        cost_cents, unpriced_calls = v2_cost(raw_by_variant["v2"][question_id])
        if cost_cents is not None:
            v2_cost_values.append(cost_cents)
        if unpriced_calls is not None:
            v2_unpriced_values.append(unpriced_calls)
        per_question.append(
            {
                "question_id": question_id,
                "question_type": question.get("question_type"),
                "expected_doc_ids": docs,
                "variants": variants,
                "v2_stage_metrics_ms": stages,
                "v2_estimated_llm_cost_cents": cost_cents,
                "v2_unpriced_calls": unpriced_calls,
                "strict_score_delta_v2_minus_legacy": variants["v2"]["combined_pct"]
                - variants["legacy"]["combined_pct"],
            }
        )

    per_type: dict[str, dict[str, Any]] = {}
    for question_type in sorted({str(row["question_type"]) for row in per_question}):
        typed_rows = [
            row for row in per_question if row["question_type"] == question_type
        ]
        per_type[question_type] = {
            variant: aggregate_scores([row["variants"][variant] for row in typed_rows])
            for variant in VARIANTS
        }
        per_type[question_type]["strict_score_delta_v2_minus_legacy_mean"] = mean(
            [float(row["strict_score_delta_v2_minus_legacy"]) for row in typed_rows]
        )

    variants_summary: dict[str, Any] = {}
    for variant in VARIANTS:
        all_latencies = [
            float(row["client_total_ms"])
            for row in raw_by_variant[variant].values()
            if isinstance(row.get("client_total_ms"), int | float)
        ]
        completed_latencies = [
            float(raw_by_variant[variant][question_id]["client_total_ms"])
            for question_id, sample in samples_by_variant[variant].items()
            if sample["status"] == "succeeded"
            and isinstance(
                raw_by_variant[variant][question_id].get("client_total_ms"),
                int | float,
            )
        ]
        variants_summary[variant] = {
            "scores": aggregate_scores(variant_scores[variant]),
            "outcome_counts": dict(
                Counter(
                    str(row.get("harness_outcome"))
                    for row in samples_by_variant[variant].values()
                )
            ),
            "sample_status_counts": dict(
                Counter(
                    str(row["status"]) for row in samples_by_variant[variant].values()
                )
            ),
            "unresolved_citations": unresolved_citation_summary(
                samples_by_variant[variant]
            ),
            "latency_ms_all_attempts": latency_stats(all_latencies),
            "latency_ms_completed_only": latency_stats(completed_latencies),
            "official_aggregate_stats_raw": official_aggregates[variant],
        }
    variants_summary["v2"]["stage_metrics_ms"] = aggregate_stage_metrics(v2_stage_rows)
    variants_summary["v2"]["estimated_llm_cost_cents"] = {
        "n": len(v2_cost_values),
        "mean": mean(v2_cost_values),
        "unpriced_call_count_n": len(v2_unpriced_values),
        "unpriced_call_count_total": sum(v2_unpriced_values),
    }
    variants_summary["legacy"]["estimated_llm_cost_cents"] = None

    return {
        "comparison_scope": (
            "Frozen 20-question diagnostic comparison. Do not infer statistical "
            "significance, winner status, or noninferiority from this summary."
        ),
        "question_count": len(question_ids),
        "variants": variants_summary,
        "per_question": per_question,
        "per_type": per_type,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-results", type=Path, required=True)
    parser.add_argument("--grade-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    summary = summarize(args.raw_results, args.grade_dir)
    with args.output.open("x") as stream:
        stream.write(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
