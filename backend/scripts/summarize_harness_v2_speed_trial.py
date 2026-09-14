"""Summarize paired v2 speed arms after official fixed-gold grading."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.summarize_harness_v2_eval import (
    aggregate_scores,
    aggregate_stage_metrics,
    expected_doc_ids,
    index_unique_rows,
    latency_stats,
    read_json_object,
    read_jsonl,
    require_official_results,
    require_sample_rows,
    require_variant_rows,
    score_sample,
    v2_cost,
    v2_stage_metrics,
)


def summarize(run: Path) -> dict[str, Any]:
    manifest = read_json_object(run / "manifest.json")
    questions = index_unique_rows(
        read_jsonl(run / "reference" / "selected_questions.jsonl"),
        "question_id",
        "reference questions",
    )
    ids = manifest["question_ids"]
    if not ids or len(set(ids)) != len(ids) or set(ids) != set(questions):
        raise ValueError("Reference and trial question IDs differ")
    output: dict[str, Any] = {"manifest": manifest, "arms": {}, "per_question": {}}
    for arm in ("control", "optimized"):
        arm_questions = index_unique_rows(
            read_jsonl(run / "grades" / arm / "v2" / "selected_questions.jsonl"),
            "question_id",
            arm,
        )
        if arm_questions != questions:
            raise ValueError("Grading reference changed between arms")
        raw = require_variant_rows(
            read_jsonl(run / f"results_{arm}.jsonl"), ids, "v2", arm
        )
        samples = require_sample_rows(run / "grades" / arm, ids, "v2")
        official, original_aggregate = require_official_results(
            run / "grades" / arm, samples, "v2"
        )
        scores, stages, costs, lengths, latencies, post_times, post_tokens = (
            [],
            [],
            [],
            [],
            [],
            [],
            [],
        )
        modes: Counter[str] = Counter()
        unknown_usage_calls = 0
        for qid in ids:
            row = raw[qid]
            if row["question"] != questions[qid]["question"] or row.get("arm") != arm:
                raise ValueError("Trial row does not match its question and arm")
            score = score_sample(
                samples[qid], official, expected_doc_ids(questions[qid])
            )
            stage = v2_stage_metrics(row)
            cost, unknown = v2_cost(row)
            decisions = [
                e
                for e in row.get("raw", {}).get("result", {}).get("events", [])
                if e["kind"] == "model_decision"
            ]
            post = decisions[1:]
            post_ms = sum(e["data"]["duration_ms"] for e in post) if post else None
            post_token_count = (
                sum(
                    e["data"]["usage_after"]["total_tokens"]
                    - e["data"]["usage_before"]["total_tokens"]
                    for e in post
                )
                if post
                else None
            )
            scores.append(score)
            stages.append(stage)
            lengths.append(len(row.get("answer", "")))
            latencies.append(row["client_total_ms"])
            if cost is not None:
                costs.append(cost)
            unknown_usage_calls += unknown or 0
            if post_ms is not None:
                post_times.append(post_ms)
            if post_token_count is not None:
                post_tokens.append(post_token_count)
            modes.update(e["data"].get("decision_mode", "unknown") for e in decisions)
            output["per_question"].setdefault(qid, {})[arm] = {
                "outcome": row["outcome"],
                "answer_characters": lengths[-1],
                "client_total_ms": latencies[-1],
                "stage_ms": stage,
                "score": score,
                "post_search_decision_ms": post_ms,
                "post_search_decision_tokens": post_token_count,
            }
        output["arms"][arm] = {
            "scores": aggregate_scores(scores),
            "official_aggregate": original_aggregate,
            "answer_characters": latency_stats(lengths),
            "client_total_ms": latency_stats(latencies),
            "stage_ms": aggregate_stage_metrics(stages),
            "post_search_decision_ms": latency_stats(post_times),
            "post_search_decision_tokens": latency_stats(post_tokens),
            "estimated_llm_cost_cents": latency_stats(costs),
            "unknown_usage_calls": unknown_usage_calls,
            "decision_modes": dict(modes),
        }
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists")
    result = summarize(args.run_dir)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
