import json
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts.summarize_harness_v2_eval import latency_stats, main, summarize


def _question(
    question_id: str,
    *,
    question_type: str = "fact",
    expected_doc_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question": f"Question {question_id}?",
        "question_type": question_type,
        "expected_doc_ids": expected_doc_ids or [],
    }


def _sample(
    question_id: str,
    *,
    status: str = "succeeded",
    harness_outcome: str = "completed",
    unresolved_citation_numbers: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "status": status,
        "harness_outcome": harness_outcome,
        "answer": "answer" if status == "succeeded" else "",
        "document_ids": ["doc-a"] if status == "succeeded" else [],
        "unresolved_citation_numbers": unresolved_citation_numbers or [],
    }


def _official(
    question_id: str,
    *,
    answer_correct: bool = True,
    completeness_pct: float = 100.0,
    document_recall_pct: float | None = None,
    invalid_extra_docs: int | None = None,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "answer_correct": answer_correct,
        "completeness_pct": completeness_pct,
        "document_recall_pct": document_recall_pct,
        "invalid_extra_docs": invalid_extra_docs,
    }


def _raw(
    question_id: str,
    variant: str,
    *,
    client_total_ms: float = 100.0,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "variant": variant,
        "client_total_ms": client_total_ms,
        "raw": raw or {"answer": "legacy"},
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload) + "\n")


def _write_variant(
    grade_dir: Path,
    variant: str,
    *,
    questions: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    official_rows: list[dict[str, Any]],
) -> None:
    variant_dir = grade_dir / variant
    variant_dir.mkdir(parents=True)
    _write_jsonl(variant_dir / "selected_questions.jsonl", questions)
    _write_jsonl(variant_dir / "samples.jsonl", samples)
    _write_json(
        variant_dir / "official_results_repeat_01.json",
        {
            "questions": official_rows,
            "aggregate_stats": {"raw_from_judge": variant},
        },
    )


def _write_eval(
    tmp_path: Path,
    *,
    questions: list[dict[str, Any]],
    samples_by_variant: dict[str, list[dict[str, Any]]],
    official_by_variant: dict[str, list[dict[str, Any]]],
    raw_rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    grade_dir = tmp_path / "grade"
    for variant in ("legacy", "v2"):
        _write_variant(
            grade_dir,
            variant,
            questions=questions,
            samples=samples_by_variant[variant],
            official_rows=official_by_variant[variant],
        )
    raw_results = tmp_path / "raw.jsonl"
    _write_jsonl(raw_results, raw_rows)
    return raw_results, grade_dir


def test_missing_judge_rows_are_rejected(tmp_path: Path) -> None:
    questions = [_question("q1")]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1")],
            "v2": [_sample("q1")],
        },
        official_by_variant={
            "legacy": [],
            "v2": [_official("q1")],
        },
        raw_rows=[_raw("q1", "legacy"), _raw("q1", "v2")],
    )

    with pytest.raises(
        ValueError,
        match="Official scored IDs must equal succeeded sample IDs for legacy",
    ):
        summarize(raw_results, grade_dir)


def test_empty_selected_question_sets_are_rejected(tmp_path: Path) -> None:
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=[],
        samples_by_variant={"legacy": [], "v2": []},
        official_by_variant={"legacy": [], "v2": []},
        raw_rows=[],
    )

    with pytest.raises(ValueError, match="Selected question set cannot be empty"):
        summarize(raw_results, grade_dir)


def test_selected_question_record_drift_is_rejected(tmp_path: Path) -> None:
    grade_dir = tmp_path / "grade"
    _write_variant(
        grade_dir,
        "legacy",
        questions=[_question("q1", expected_doc_ids=["doc-a"])],
        samples=[_sample("q1")],
        official_rows=[_official("q1")],
    )
    _write_variant(
        grade_dir,
        "v2",
        questions=[_question("q1", expected_doc_ids=["doc-b"])],
        samples=[_sample("q1")],
        official_rows=[_official("q1")],
    )
    raw_results = tmp_path / "raw.jsonl"
    _write_jsonl(raw_results, [_raw("q1", "legacy"), _raw("q1", "v2")])

    with pytest.raises(
        ValueError,
        match="Selected question records differ between variants",
    ):
        summarize(raw_results, grade_dir)


@pytest.mark.parametrize(
    ("official_row", "message"),
    [
        (
            {
                **_official("q1", document_recall_pct=100.0, invalid_extra_docs=0),
                "answer_correct": "false",
            },
            "answer_correct",
        ),
        (
            {
                **_official("q1", document_recall_pct=100.0, invalid_extra_docs=0),
                "completeness_pct": float("nan"),
            },
            "completeness_pct",
        ),
        (
            {
                **_official("q1", document_recall_pct=100.0, invalid_extra_docs=0),
                "document_recall_pct": 101.0,
            },
            "document_recall_pct",
        ),
        (
            {
                **_official("q1", document_recall_pct=100.0, invalid_extra_docs=0),
                "invalid_extra_docs": -1,
            },
            "invalid_extra_docs",
        ),
    ],
)
def test_official_result_fields_are_strictly_validated(
    tmp_path: Path,
    official_row: dict[str, Any],
    message: str,
) -> None:
    questions = [_question("q1", expected_doc_ids=["doc-a"])]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1")],
            "v2": [_sample("q1")],
        },
        official_by_variant={
            "legacy": [official_row],
            "v2": [_official("q1")],
        },
        raw_rows=[_raw("q1", "legacy"), _raw("q1", "v2")],
    )

    with pytest.raises(ValueError, match=message):
        summarize(raw_results, grade_dir)


def test_failed_samples_score_zero_and_remain_in_denominator(tmp_path: Path) -> None:
    questions = [
        _question("q1", expected_doc_ids=["doc-a"]),
        _question("q2", expected_doc_ids=["doc-b"]),
    ]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [
                _sample("q1"),
                _sample("q2", status="failed", harness_outcome="timeout"),
            ],
            "v2": [
                _sample("q1"),
                _sample("q2", status="failed", harness_outcome="blocked"),
            ],
        },
        official_by_variant={
            "legacy": [
                _official(
                    "q1",
                    completeness_pct=80.0,
                    document_recall_pct=70.0,
                    invalid_extra_docs=2,
                )
            ],
            "v2": [
                _official(
                    "q1",
                    completeness_pct=60.0,
                    document_recall_pct=30.0,
                    invalid_extra_docs=4,
                )
            ],
        },
        raw_rows=[
            _raw("q1", "legacy", client_total_ms=100),
            _raw("q2", "legacy", client_total_ms=200),
            _raw("q1", "v2", client_total_ms=300),
            _raw("q2", "v2", client_total_ms=400),
        ],
    )

    summary = summarize(raw_results, grade_dir)

    legacy_scores = summary["variants"]["legacy"]["scores"]
    assert legacy_scores["completion_rate_pct"] == 50.0
    assert legacy_scores["combined_pct_mean"] == 40.0
    assert legacy_scores["document_recall_pct_mean_applicable"] == 35.0
    assert legacy_scores["invalid_extra_docs_mean"] == 1.0
    assert summary["per_question"][1]["variants"]["legacy"]["combined_pct"] == 0.0
    assert summary["variants"]["legacy"]["latency_ms_completed_only"]["n"] == 1


def test_unresolved_citations_are_reported_separately_from_official_scores(
    tmp_path: Path,
) -> None:
    questions = [_question("q1"), _question("q2")]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [
                _sample("q1", unresolved_citation_numbers=[7, 9]),
                _sample("q2"),
            ],
            "v2": [
                _sample("q1"),
                _sample("q2", unresolved_citation_numbers=[4]),
            ],
        },
        official_by_variant={
            "legacy": [_official("q1"), _official("q2")],
            "v2": [_official("q1"), _official("q2")],
        },
        raw_rows=[
            _raw("q1", "legacy"),
            _raw("q2", "legacy"),
            _raw("q1", "v2"),
            _raw("q2", "v2"),
        ],
    )

    summary = summarize(raw_results, grade_dir)

    assert summary["variants"]["legacy"]["unresolved_citations"] == {
        "count": 2,
        "question_ids": ["q1"],
    }
    assert summary["variants"]["v2"]["unresolved_citations"] == {
        "count": 1,
        "question_ids": ["q2"],
    }
    assert summary["variants"]["legacy"]["scores"]["invalid_extra_docs_mean"] is None
    assert (
        summary["variants"]["legacy"]["scores"]["invalid_extra_docs_applicable_n"] == 0
    )


def test_document_recall_mean_only_uses_questions_with_expected_docs(
    tmp_path: Path,
) -> None:
    questions = [
        _question("q1", expected_doc_ids=["doc-a"]),
        _question("q2", expected_doc_ids=[]),
    ]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1"), _sample("q2")],
            "v2": [_sample("q1"), _sample("q2")],
        },
        official_by_variant={
            "legacy": [
                _official("q1", document_recall_pct=50.0, invalid_extra_docs=0),
                _official("q2"),
            ],
            "v2": [
                _official("q1", document_recall_pct=25.0, invalid_extra_docs=0),
                _official("q2"),
            ],
        },
        raw_rows=[
            _raw("q1", "legacy"),
            _raw("q2", "legacy"),
            _raw("q1", "v2"),
            _raw("q2", "v2"),
        ],
    )

    summary = summarize(raw_results, grade_dir)

    assert (
        summary["variants"]["legacy"]["scores"]["document_recall_pct_mean_applicable"]
        == 50.0
    )
    assert summary["variants"]["legacy"]["scores"]["document_recall_applicable_n"] == 1
    assert (
        summary["per_question"][1]["variants"]["legacy"]["document_recall_pct"] is None
    )
    assert (
        summary["per_question"][1]["variants"]["legacy"]["invalid_extra_docs"] is None
    )
    assert (
        summary["variants"]["legacy"]["scores"]["invalid_extra_docs_applicable_n"] == 1
    )


def test_no_expected_docs_accepts_null_official_recall_and_extra_docs(
    tmp_path: Path,
) -> None:
    questions = [
        _question("q1", expected_doc_ids=[]),
        _question("q2", expected_doc_ids=[]),
    ]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1"), _sample("q2", status="failed")],
            "v2": [_sample("q1"), _sample("q2", status="failed")],
        },
        official_by_variant={
            "legacy": [_official("q1")],
            "v2": [_official("q1")],
        },
        raw_rows=[
            _raw("q1", "legacy"),
            _raw("q2", "legacy"),
            _raw("q1", "v2"),
            _raw("q2", "v2"),
        ],
    )

    summary = summarize(raw_results, grade_dir)

    legacy_scores = summary["variants"]["legacy"]["scores"]
    assert legacy_scores["document_recall_pct_mean_applicable"] is None
    assert legacy_scores["document_recall_applicable_n"] == 0
    assert legacy_scores["invalid_extra_docs_mean"] is None
    assert legacy_scores["invalid_extra_docs_applicable_n"] == 0
    assert (
        summary["per_question"][0]["variants"]["legacy"]["invalid_extra_docs"] is None
    )
    assert (
        summary["per_question"][1]["variants"]["legacy"]["invalid_extra_docs"] is None
    )


@pytest.mark.parametrize(
    ("official_row", "message"),
    [
        (
            _official("q1", document_recall_pct=0.0, invalid_extra_docs=None),
            "document_recall_pct must be null",
        ),
        (
            _official("q1", document_recall_pct=None, invalid_extra_docs=0),
            "invalid_extra_docs must be null",
        ),
    ],
)
def test_no_expected_docs_rejects_non_null_recall_or_extra_docs(
    tmp_path: Path,
    official_row: dict[str, Any],
    message: str,
) -> None:
    questions = [_question("q1", expected_doc_ids=[])]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1")],
            "v2": [_sample("q1")],
        },
        official_by_variant={
            "legacy": [official_row],
            "v2": [_official("q1")],
        },
        raw_rows=[_raw("q1", "legacy"), _raw("q1", "v2")],
    )

    with pytest.raises(ValueError, match=message):
        summarize(raw_results, grade_dir)


def test_v2_stage_metrics_and_cost_are_reported_from_raw_response(
    tmp_path: Path,
) -> None:
    questions = [_question("q1")]
    v2_raw = {
        "setup_ms": 11,
        "result": {
            "total_ms": 150,
            "usage": {"cost_cents": 1.5, "unpriced_calls": 2},
            "events": [
                {"kind": "model_decision", "data": {"duration_ms": 10}},
                {"kind": "model_decision", "data": {"duration_ms": 15}},
                {
                    "kind": "tool_call",
                    "data": {"tool": "internal_search", "duration_ms": 25},
                },
                {"kind": "tool_call", "data": {"tool": "other", "duration_ms": 99}},
            ],
            "receipts": [
                {
                    "tool_name": "internal_search",
                    "tool_receipt": {
                        "retrieval_ms": 7,
                        "answer_synthesis_ms": 8,
                    },
                },
                {"retrieval_ms": 3},
            ],
        },
    }
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1")],
            "v2": [_sample("q1")],
        },
        official_by_variant={
            "legacy": [_official("q1")],
            "v2": [_official("q1")],
        },
        raw_rows=[
            _raw("q1", "legacy"),
            _raw("q1", "v2", raw=v2_raw),
        ],
    )

    summary = summarize(raw_results, grade_dir)

    metrics = summary["per_question"][0]["v2_stage_metrics_ms"]
    assert metrics["setup_ms"] == 11.0
    assert metrics["outer_model_decision_ms"] == 25.0
    assert metrics["non_search_loop_ms"] == 125.0
    assert metrics["internal_search_tool_ms"] == 25.0
    assert metrics["internal_search_retrieval_ms"] == 7.0
    assert metrics["internal_search_answer_synthesis_ms"] == 8.0
    assert summary["variants"]["v2"]["estimated_llm_cost_cents"]["mean"] == 1.5
    assert (
        summary["variants"]["v2"]["estimated_llm_cost_cents"][
            "unpriced_call_count_total"
        ]
        == 2
    )
    stage_summary = summary["variants"]["v2"]["stage_metrics_ms"]
    assert stage_summary["internal_search_tool_ms"]["n"] == 1
    assert stage_summary["internal_search_tool_ms"]["p50"] == 25.0
    assert stage_summary["internal_search_tool_ms"]["p90"] == 25.0
    assert stage_summary["internal_search_tool_ms"]["p99"] == 25.0
    assert stage_summary["internal_search_tool_ms"]["max"] == 25.0


def test_v2_stage_metrics_unknown_when_raw_response_lacks_result(
    tmp_path: Path,
) -> None:
    questions = [_question("q1")]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1")],
            "v2": [_sample("q1")],
        },
        official_by_variant={
            "legacy": [_official("q1")],
            "v2": [_official("q1")],
        },
        raw_rows=[
            _raw("q1", "legacy"),
            _raw("q1", "v2", raw={"setup_ms": 11}),
        ],
    )

    summary = summarize(raw_results, grade_dir)

    assert summary["per_question"][0]["v2_stage_metrics_ms"] == {
        "setup_ms": None,
        "outer_model_decision_ms": None,
        "non_search_loop_ms": None,
        "internal_search_tool_ms": None,
        "internal_search_retrieval_ms": None,
        "internal_search_answer_synthesis_ms": None,
    }


def test_missing_internal_search_stage_measurement_makes_stage_unknown(
    tmp_path: Path,
) -> None:
    questions = [_question("q1")]
    v2_raw = {
        "setup_ms": 11,
        "result": {
            "events": [
                {"kind": "tool_timeout", "data": {"tool": "internal_search"}},
            ],
            "receipts": [
                {
                    "tool_name": "internal_search",
                    "tool_receipt": {"retrieval_ms": 7},
                }
            ],
        },
    }
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1")],
            "v2": [_sample("q1")],
        },
        official_by_variant={
            "legacy": [_official("q1")],
            "v2": [_official("q1")],
        },
        raw_rows=[
            _raw("q1", "legacy"),
            _raw("q1", "v2", raw=v2_raw),
        ],
    )

    summary = summarize(raw_results, grade_dir)

    metrics = summary["per_question"][0]["v2_stage_metrics_ms"]
    assert metrics["internal_search_tool_ms"] is None
    assert metrics["internal_search_retrieval_ms"] == 7.0
    assert metrics["internal_search_answer_synthesis_ms"] is None


def test_percentile_arithmetic_uses_linear_interpolation() -> None:
    stats = latency_stats([0.0, 100.0, 200.0])

    assert stats["p50"] == 100.0
    assert stats["p90"] == 180.0
    assert stats["p99"] == 198.0
    assert stats["percentile_method"] == (
        "linear interpolation; small-sample descriptive only"
    )


def test_cli_refuses_to_overwrite_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    questions = [_question("q1")]
    raw_results, grade_dir = _write_eval(
        tmp_path,
        questions=questions,
        samples_by_variant={
            "legacy": [_sample("q1")],
            "v2": [_sample("q1")],
        },
        official_by_variant={
            "legacy": [_official("q1")],
            "v2": [_official("q1")],
        },
        raw_rows=[_raw("q1", "legacy"), _raw("q1", "v2")],
    )
    output = tmp_path / "summary.json"
    output.write_text("{}")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_harness_v2_eval.py",
            "--raw-results",
            str(raw_results),
            "--grade-dir",
            str(grade_dir),
            "--output",
            str(output),
        ],
    )

    with pytest.raises(FileExistsError):
        main()
