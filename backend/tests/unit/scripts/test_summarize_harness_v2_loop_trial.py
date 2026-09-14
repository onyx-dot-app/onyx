import json
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import summarize_harness_v2_loop_trial as loop_summary


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _question(question_id: str, question_type: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": f"What about {question_id}?",
        "expected_doc_ids": ["doc-a"],
    }


def _sample(question_id: str, status: str = "succeeded") -> dict[str, Any]:
    return {
        "question_id": question_id,
        "variant": "v2",
        "status": status,
        "answer": "answer" if status == "succeeded" else "",
    }


def _official(
    question_id: str, correctness: bool, completeness_pct: float
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "answer_correct": correctness,
        "completeness_pct": completeness_pct,
        "document_recall_pct": 100.0,
        "invalid_extra_docs": 0,
    }


def _raw_result(
    question: dict[str, Any],
    arm: str,
    *,
    initial_decision_ms: float,
    post_decision_ms: float,
    context_prep_ms: float,
    search_ms: float,
    total_ms: float,
) -> dict[str, Any]:
    return {
        "question_id": question["question_id"],
        "question": question["question"],
        "variant": "v2",
        "arm": arm,
        "answer": f"{arm} answer",
        "outcome": "completed",
        "client_total_ms": total_ms + 5,
        "raw": {
            "setup_ms": 3,
            "result": {
                "answer": f"{arm} answer",
                "outcome": "completed",
                "total_ms": total_ms,
                "usage": {"cost_cents": 1.0, "unpriced_calls": 0},
                "events": [
                    {
                        "kind": "model_decision",
                        "data": {
                            "duration_ms": initial_decision_ms,
                            "decision_mode": "standard",
                            "usage_before": {"total_tokens": 0},
                            "usage_after": {"total_tokens": 10},
                        },
                    },
                    {
                        "kind": "context_preparation",
                        "data": {"duration_ms": context_prep_ms},
                    },
                    {
                        "kind": "tool_call",
                        "data": {
                            "tool": "internal_search",
                            "duration_ms": search_ms,
                        },
                    },
                    {
                        "kind": "model_decision",
                        "data": {
                            "duration_ms": post_decision_ms,
                            "decision_mode": "minimal_compact",
                            "usage_before": {"total_tokens": 10},
                            "usage_after": {"total_tokens": 20},
                        },
                    },
                ],
                "receipts": [
                    {
                        "tool_name": "internal_search",
                        "tool_receipt": {
                            "retrieval_ms": search_ms / 2,
                            "answer_synthesis_ms": search_ms / 2,
                        },
                    }
                ],
            },
        },
    }


def _write_arm_grades(
    run_dir: Path,
    arm: str,
    questions: list[dict[str, Any]],
    official_rows: list[dict[str, Any]],
    failed_ids: set[str] | None = None,
) -> None:
    failed_ids = failed_ids or set()
    arm_dir = run_dir / "grades" / arm / "v2"
    _write_jsonl(arm_dir / "selected_questions.jsonl", questions)
    _write_jsonl(
        arm_dir / "samples.jsonl",
        [
            _sample(
                question["question_id"],
                status="failed"
                if question["question_id"] in failed_ids
                else "succeeded",
            )
            for question in questions
        ],
    )
    _write_json(
        arm_dir / "official_results_repeat_01.json",
        {
            "questions": official_rows,
            "aggregate_stats": {"arm": arm},
        },
    )


def _write_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    questions = [
        _question("q1", "basic"),
        _question("q2", "aggregate"),
        _question("q3", "aggregate"),
        _question("q4", "basic"),
    ]
    _write_json(
        run_dir / "manifest.json",
        {
            "question_ids": [question["question_id"] for question in questions],
            "arms": {"control": {}, "optimized": {}},
        },
    )
    _write_jsonl(run_dir / "reference" / "selected_questions.jsonl", questions)
    _write_jsonl(
        run_dir / "results_control.jsonl",
        [
            _raw_result(
                questions[0],
                "control",
                initial_decision_ms=100,
                post_decision_ms=50,
                context_prep_ms=10,
                search_ms=400,
                total_ms=700,
            ),
            _raw_result(
                questions[1],
                "control",
                initial_decision_ms=200,
                post_decision_ms=60,
                context_prep_ms=20,
                search_ms=500,
                total_ms=900,
            ),
            _raw_result(
                questions[2],
                "control",
                initial_decision_ms=300,
                post_decision_ms=70,
                context_prep_ms=30,
                search_ms=600,
                total_ms=1100,
            ),
            _raw_result(
                questions[3],
                "control",
                initial_decision_ms=400,
                post_decision_ms=80,
                context_prep_ms=40,
                search_ms=700,
                total_ms=1300,
            ),
        ],
    )
    _write_jsonl(
        run_dir / "results_optimized.jsonl",
        [
            _raw_result(
                questions[0],
                "optimized",
                initial_decision_ms=80,
                post_decision_ms=25,
                context_prep_ms=8,
                search_ms=400,
                total_ms=620,
            ),
            _raw_result(
                questions[1],
                "optimized",
                initial_decision_ms=160,
                post_decision_ms=35,
                context_prep_ms=16,
                search_ms=500,
                total_ms=780,
            ),
            _raw_result(
                questions[2],
                "optimized",
                initial_decision_ms=240,
                post_decision_ms=45,
                context_prep_ms=24,
                search_ms=600,
                total_ms=960,
            ),
            _raw_result(
                questions[3],
                "optimized",
                initial_decision_ms=320,
                post_decision_ms=55,
                context_prep_ms=32,
                search_ms=700,
                total_ms=1140,
            ),
        ],
    )
    control_rows = [
        json.loads(line)
        for line in (run_dir / "results_control.jsonl").read_text().splitlines()
    ]
    control_rows[2]["raw"]["result"].pop("total_ms")
    _write_jsonl(run_dir / "results_control.jsonl", control_rows)
    _write_arm_grades(
        run_dir,
        "control",
        questions,
        [
            _official("q1", True, 100.0),
            _official("q2", True, 80.0),
            _official("q4", True, 100.0),
        ],
        failed_ids={"q3"},
    )
    _write_arm_grades(
        run_dir,
        "optimized",
        questions,
        [
            _official("q1", True, 80.0),
            _official("q2", True, 90.0),
            _official("q3", True, 100.0),
            _official("q4", True, 95.0),
        ],
    )
    return run_dir


def test_loop_trial_summary_adds_type_timing_and_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(loop_summary, "BOOTSTRAP_REPLICATES", 64)
    run_dir = _write_run_dir(tmp_path)

    summary = loop_summary.summarize(run_dir)

    assert summary["question_count"] == 4
    assert (
        summary["raw_summary"]["arms"]["control"]["scores"]["combined_pct_mean"] == 70.0
    )
    assert summary["per_type"]["aggregate"]["control"]["combined_pct_mean"] == 40.0
    assert summary["per_type"]["aggregate"]["optimized"]["combined_pct_mean"] == 95.0
    assert summary["arms"]["control"]["initial_decision_ms"]["mean"] == 250.0
    assert summary["arms"]["optimized"]["context_preparation_ms"]["mean"] == 20.0
    assert (
        summary["per_question"][0]["non_search_loop_delta_ms_optimized_minus_control"]
        == -80.0
    )
    assert summary["per_question"][2]["control_score"]["succeeded"] is False
    assert (
        summary["bootstrap_95ci"]["difference_direction"] == "optimized_minus_control"
    )
    assert summary["bootstrap_95ci"]["valid_paired_sample_counts"] == {
        "non_search_loop_ms": 3,
        "combined_quality_pct": 4,
    }
    assert summary["bootstrap_95ci"]["mean_non_search_loop_ms"]["replicates"] == 64
    assert (
        summary["bootstrap_95ci"]["median_paired_non_search_delta_ms"]["replicates"]
        == 64
    )
    assert (
        summary["bootstrap_95ci"][
            "median_non_search_loop_ms_difference_of_marginal_medians"
        ]["replicates"]
        == 64
    )
    assert "median_non_search_loop_ms" not in summary["bootstrap_95ci"]
    assert summary["quality_regressions"][0]["question_id"] == "q1"
    assert (
        summary["quality_regressions"][0]["combined_delta_optimized_minus_control"]
        == -20.0
    )
    assert summary["quality_regressions"][0]["notable_10pt_or_more"] is True
    assert summary["quality_regressions"][1]["question_id"] == "q4"
    assert summary["quality_regressions"][1]["notable_10pt_or_more"] is False
    assert [row["question_id"] for row in summary["raw_rows"]["control"]] == [
        "q1",
        "q2",
        "q3",
        "q4",
    ]


def test_cli_refuses_to_overwrite_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = _write_run_dir(tmp_path)
    output = tmp_path / "summary.json"
    output.write_text("{}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_harness_v2_loop_trial.py",
            "--run-dir",
            str(run_dir),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit):
        loop_summary.main()
