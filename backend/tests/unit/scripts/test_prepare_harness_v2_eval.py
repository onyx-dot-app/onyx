import json
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts.prepare_harness_v2_eval import (
    cited_documents,
    export_variant,
    main,
    select_questions,
)


def _question(
    question_id: str,
    question_type: str = "fact",
    question: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": question or f"Question {question_id}?",
        **extra,
    }


def _result(
    question_id: str,
    variant: str,
    *,
    question: str | None = None,
    answer: str = "Answer [1]",
    outcome: str = "completed",
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "variant": variant,
        "question": question or f"Question {question_id}?",
        "answer": answer,
        "outcome": outcome,
        "raw": raw or {},
        "client_total_ms": 123,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_select_questions_is_deterministic_by_type_and_ignores_gold_fields() -> None:
    rows = [
        _question("fact-1", "fact", gold_answer="alpha"),
        _question("fact-2", "fact", gold_answer="bravo"),
        _question("fact-3", "fact", gold_answer="charlie"),
        _question("multi-1", "multi", gold_documents=["doc-a"]),
        _question("multi-2", "multi", gold_documents=["doc-b"]),
        _question("multi-3", "multi", gold_documents=["doc-c"]),
    ]
    rows_with_different_order_and_gold = [
        {**row, "gold_answer": f"changed-{index}", "gold_documents": ["changed"]}
        for index, row in enumerate(reversed(rows))
    ]

    selected = select_questions(rows, per_type=2, seed="stable-seed")
    selected_again = select_questions(
        rows_with_different_order_and_gold,
        per_type=2,
        seed="stable-seed",
    )

    assert [row["question_id"] for row in selected] == [
        row["question_id"] for row in selected_again
    ]
    assert [row["question_type"] for row in selected].count("fact") == 2
    assert [row["question_type"] for row in selected].count("multi") == 2


def test_select_questions_rejects_duplicate_source_ids() -> None:
    rows = [
        _question("duplicate", "fact"),
        _question("duplicate", "multi"),
    ]

    with pytest.raises(ValueError, match="Duplicate source question IDs"):
        select_questions(rows, per_type=1, seed="stable-seed")


def test_select_cli_input_only_export_does_not_leak_gold_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "selection"
    rows = [
        _question(
            "fact-1", "fact", gold_answer="secret-a", gold_document_ids=["doc-a"]
        ),
        _question(
            "fact-2", "fact", gold_answer="secret-b", gold_document_ids=["doc-b"]
        ),
        _question(
            "multi-1", "multi", gold_answer="secret-c", gold_document_ids=["doc-c"]
        ),
        _question(
            "multi-2", "multi", gold_answer="secret-d", gold_document_ids=["doc-d"]
        ),
    ]
    _write_jsonl(source, rows)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_harness_v2_eval.py",
            "select",
            "--source",
            str(source),
            "--output",
            str(output),
            "--per-type",
            "2",
            "--seed",
            "stable-seed",
        ],
    )

    main()

    question_rows = _read_jsonl(output / "questions.jsonl")
    assert question_rows
    assert all(set(row) == {"question_id", "question"} for row in question_rows)
    assert "secret" not in (output / "questions.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("row", "expected_docs", "expected_unresolved"),
    [
        (
            _result(
                "q1",
                "legacy",
                answer="Uses [[1]]() then repeats [[1]]() and misses [[7]]().",
                raw={
                    "citation_info": [
                        {"citation_number": 1, "document_id": "legacy-doc"},
                    ]
                },
            ),
            ["legacy-doc"],
            [7],
        ),
        (
            _result(
                "q1",
                "v2",
                answer="Uses [1], groups [2, 3], repeats [2], and misses [9].",
                raw={
                    "result": {
                        "citation_mapping": {
                            "1": "v2-doc-a",
                            "2": "v2-doc-b",
                            "3": "v2-doc-b",
                        }
                    }
                },
            ),
            ["v2-doc-a", "v2-doc-b"],
            [9],
        ),
    ],
)
def test_cited_documents_extracts_common_citation_formats(
    row: dict[str, Any],
    expected_docs: list[str],
    expected_unresolved: list[int],
) -> None:
    assert cited_documents(row) == (expected_docs, expected_unresolved)


def test_export_variant_masks_failed_answers_but_keeps_sample_details() -> None:
    questions = [_question("q1")]
    results = [
        _result(
            "q1",
            "v2",
            answer="Partial answer [1]",
            outcome="timeout",
            raw={"result": {"citation_mapping": {"1": "doc-1"}}},
        )
    ]

    answers, samples = export_variant(questions, results, "v2")

    assert answers == [
        {
            "question_id": "q1",
            "answer": "",
            "document_ids": [],
            "document_id_semantics": "cited",
        }
    ]
    assert samples == [
        {
            "question_id": "q1",
            "answer": "",
            "document_ids": [],
            "document_id_semantics": "cited",
            "repeat_index": 1,
            "status": "failed",
            "harness_outcome": "timeout",
            "raw_answer": "Partial answer [1]",
            "raw_cited_document_ids": ["doc-1"],
            "unresolved_citation_numbers": [],
            "client_total_ms": 123,
        }
    ]


@pytest.mark.parametrize(
    "results",
    [
        [_result("q1", "legacy")],
        [_result("q1", "v2"), _result("q1", "v2", answer="Other [1]")],
    ],
)
def test_export_variant_rejects_missing_or_duplicate_question_variant(
    results: list[dict[str, Any]],
) -> None:
    questions = [_question("q1")]

    with pytest.raises(ValueError, match="Expected exactly one result"):
        export_variant(questions, results, "v2")


def test_merge_keeps_fixed_control_and_failed_new_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    control = _result("q1", "legacy", answer="unchanged control")
    old_candidate = _result("q1", "v2", answer="old answer")
    new_candidate = _result("q1", "v2", answer="partial answer", outcome="blocked")
    baseline, candidate, output = (
        tmp_path / "baseline.jsonl",
        tmp_path / "candidate.jsonl",
        tmp_path / "merged.jsonl",
    )
    _write_jsonl(baseline, [control, old_candidate])
    _write_jsonl(candidate, [new_candidate])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_harness_v2_eval.py",
            "merge",
            "--baseline-results",
            str(baseline),
            "--candidate-results",
            str(candidate),
            "--output",
            str(output),
        ],
    )
    main()
    assert _read_jsonl(output) == [control, new_candidate]
