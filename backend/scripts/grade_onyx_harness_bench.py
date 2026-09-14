"""Grade a frozen run with EnterpriseRAG's official fixed-gold evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path
from typing import Any


class GradeInputError(ValueError):
    pass


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GradeInputError(
                    f"Invalid JSON on line {line_number}: {path}"
                ) from exc
            if not isinstance(row, dict):
                raise GradeInputError(
                    f"Expected JSON object on line {line_number}: {path}"
                )
            rows.append(row)
    return rows


def latest_rows_for_repeat(
    samples_path: Path, repeat: int
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(samples_path):
        if row.get("repeat_index") == repeat and isinstance(
            row.get("question_id"), str
        ):
            rows[row["question_id"]] = row
    return rows


def checked_percentage(value: Any, *, question_id: str, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GradeInputError(f"Invalid {field} for {question_id}: {value!r}")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= 100:
        raise GradeInputError(f"Invalid {field} for {question_id}: {value!r}")
    return numeric


def validate_grade_inputs(
    *,
    selected_questions_path: Path,
    answers_path: Path,
    samples_path: Path,
    repeat: int,
    allow_failed_samples: bool,
) -> bool:
    questions = read_jsonl(selected_questions_path)
    answers = read_jsonl(answers_path)
    samples_by_question = latest_rows_for_repeat(samples_path, repeat)

    raw_question_ids = [row.get("question_id") for row in questions]
    raw_answer_ids = [row.get("question_id") for row in answers]
    if not all(isinstance(question_id, str) for question_id in raw_question_ids):
        raise GradeInputError("Selected questions must all have string question_id")
    if not all(isinstance(question_id, str) for question_id in raw_answer_ids):
        raise GradeInputError("Answers must all have string question_id")
    question_ids = [str(question_id) for question_id in raw_question_ids]
    answer_ids = [str(question_id) for question_id in raw_answer_ids]
    if len(set(question_ids)) != len(question_ids):
        raise GradeInputError("Selected questions contain duplicate question IDs")
    if len(set(answer_ids)) != len(answer_ids):
        raise GradeInputError("Answers contain duplicate question IDs")
    if set(answer_ids) != set(question_ids):
        raise GradeInputError(
            "Answers must contain exactly one row for every selected question"
        )

    missing_samples = sorted(set(question_ids) - set(samples_by_question))
    if missing_samples:
        raise GradeInputError(
            f"Missing sample rows for repeat {repeat}: {missing_samples}"
        )

    answers_by_question = {row["question_id"]: row for row in answers}
    diagnostic = False
    for question_id in sorted(set(question_ids)):
        sample = samples_by_question[question_id]
        status = sample.get("status")
        answer = answers_by_question[question_id]
        answer_text = answer.get("answer", "")
        if answer_text != sample.get("answer", ""):
            raise GradeInputError(f"Answer export does not match sample: {question_id}")
        if answer.get("document_ids", []) != sample.get("document_ids", []):
            raise GradeInputError(
                f"Document ID export does not match sample: {question_id}"
            )
        if status == "contaminated":
            raise GradeInputError(
                f"Refusing to grade contaminated sample: {question_id}"
            )
        if status == "succeeded":
            continue
        if not allow_failed_samples:
            raise GradeInputError(
                f"Refusing to grade non-succeeded sample: {question_id}"
            )
        if status != "failed":
            raise GradeInputError(
                f"Diagnostic grading only permits status='failed': {question_id}"
            )
        if not isinstance(answer_text, str) or answer_text.strip():
            raise GradeInputError(
                "Diagnostic grading only permits failed samples with empty answers: "
                f"{question_id}"
            )
        diagnostic = True
    return diagnostic


def build_failure_adjusted_report(
    *,
    result_path: Path,
    selected_questions_path: Path,
    samples_path: Path,
    repeat: int,
) -> dict[str, Any]:
    result = json.loads(result_path.read_text())
    aggregate = result.get("aggregate_stats")
    if not isinstance(aggregate, dict):
        raise GradeInputError(f"Official result has no aggregate_stats: {result_path}")

    selected_questions = read_jsonl(selected_questions_path)
    requested_question_ids = [
        row["question_id"]
        for row in selected_questions
        if isinstance(row.get("question_id"), str)
    ]
    expected_by_question = {
        row["question_id"]: row.get("expected_doc_ids", [])
        for row in selected_questions
        if isinstance(row.get("question_id"), str)
    }
    latest_samples = latest_rows_for_repeat(samples_path, repeat)
    failed_question_ids = sorted(
        question_id
        for question_id in requested_question_ids
        if (latest_samples.get(question_id) or {}).get("status") == "failed"
    )
    succeeded_question_ids = sorted(
        question_id
        for question_id in requested_question_ids
        if (latest_samples.get(question_id) or {}).get("status") == "succeeded"
    )
    scored_questions = [
        row
        for row in result.get("questions", [])
        if isinstance(row, dict) and isinstance(row.get("question_id"), str)
    ]
    scored_count = len(scored_questions)
    requested_count = len(requested_question_ids)
    if requested_count == 0:
        raise GradeInputError("No selected questions found")
    scored_question_ids = [str(row["question_id"]) for row in scored_questions]
    duplicate_scored_ids = sorted(
        question_id
        for question_id in set(scored_question_ids)
        if scored_question_ids.count(question_id) > 1
    )
    if duplicate_scored_ids:
        raise GradeInputError(
            f"Official result contains duplicate question IDs: {duplicate_scored_ids}"
        )
    unexpected_scored_ids = sorted(
        set(scored_question_ids) - set(requested_question_ids)
    )
    if unexpected_scored_ids:
        raise GradeInputError(
            f"Official result contains unexpected question IDs: {unexpected_scored_ids}"
        )
    overlap = sorted(set(scored_question_ids) & set(failed_question_ids))
    if overlap:
        raise GradeInputError(f"Official result scored failed question IDs: {overlap}")
    missing_succeeded_grades = sorted(
        set(succeeded_question_ids) - set(scored_question_ids)
    )
    if missing_succeeded_grades:
        raise GradeInputError(
            "Official result is missing grades for succeeded samples: "
            f"{missing_succeeded_grades}"
        )

    def mean(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 2)

    correctness_values: list[float] = []
    completeness_values: list[float] = []
    combined_values: list[float] = []
    recall_values: list[float] = []
    for row in scored_questions:
        question_id = str(row["question_id"])
        answer_correct = row.get("answer_correct")
        if not isinstance(answer_correct, bool):
            raise GradeInputError(
                f"Invalid answer_correct for {question_id}: {answer_correct!r}"
            )
        completeness = checked_percentage(
            row.get("completeness_pct"),
            question_id=question_id,
            field="completeness_pct",
        )
        correctness_values.append(100.0 if answer_correct else 0.0)
        completeness_values.append(completeness)
        combined_values.append(completeness if answer_correct else 0.0)
        if expected_by_question.get(question_id):
            recall_values.append(
                checked_percentage(
                    row.get("document_recall_pct"),
                    question_id=question_id,
                    field="document_recall_pct",
                )
            )
    correctness_values.extend([0.0] * len(failed_question_ids))
    completeness_values.extend([0.0] * len(failed_question_ids))
    combined_values.extend([0.0] * len(failed_question_ids))
    failed_recall_question_ids = [
        question_id
        for question_id in failed_question_ids
        if expected_by_question.get(question_id)
    ]
    recall_values.extend([0.0] * len(failed_recall_question_ids))
    scored_question_id_set = set(scored_question_ids)
    recall_applicable_question_ids = sorted(
        question_id
        for question_id in requested_question_ids
        if expected_by_question.get(question_id)
    )
    return {
        "diagnostic": True,
        "method": (
            "Adds zero-score penalty rows for failed empty-answer samples skipped "
            "by the official grader."
        ),
        "repeat": repeat,
        "requested_count": requested_count,
        "scored_count": scored_count,
        "failed_count": len(failed_question_ids),
        "recall_applicable_count": len(recall_applicable_question_ids),
        "scored_recall_applicable_count": len(recall_values)
        - len(failed_recall_question_ids),
        "failed_recall_applicable_count": len(failed_recall_question_ids),
        "official_skipped_rows": aggregate.get("skipped_rows"),
        "failed_question_ids": failed_question_ids,
        "unscored_question_ids": sorted(
            set(requested_question_ids) - scored_question_id_set
        ),
        "official_aggregate_stats": aggregate,
        "failure_adjusted_stats": {
            "average_correctness_pct": mean(correctness_values),
            "average_completeness_pct": mean(completeness_values),
            "combined_correctness_completeness_score": mean(combined_values),
            "average_recall_pct": mean(recall_values),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-repo", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--parallelism", type=int, default=8)
    parser.add_argument(
        "--allow-failed-samples",
        action="store_true",
        help="Grade failed empty-answer rows as penalized diagnostic results.",
    )
    args = parser.parse_args()
    repo = args.benchmark_repo.resolve()
    run_dir = args.run_dir.resolve()
    questions = run_dir / "selected_questions.jsonl"
    answers = run_dir / f"answers_repeat_{args.repeat:02d}.jsonl"
    samples = run_dir / "samples.jsonl"
    result_path = run_dir / f"official_results_repeat_{args.repeat:02d}.json"
    metadata_path = run_dir / f"judge_manifest_repeat_{args.repeat:02d}.json"
    adjusted_path = (
        run_dir / f"diagnostic_failure_adjusted_repeat_{args.repeat:02d}.json"
    )
    interpreter = repo / ".venv/bin/python"
    for path in (questions, answers, samples, interpreter):
        if not path.is_file():
            parser.error(f"Required file missing: {path}")
    if result_path.exists() or metadata_path.exists() or adjusted_path.exists():
        parser.error(
            "Judge artifacts already exist; preserve them and use a separate run directory"
        )
    if args.parallelism < 1 or args.repeat < 1:
        parser.error("parallelism and repeat must be positive")
    try:
        diagnostic = validate_grade_inputs(
            selected_questions_path=questions,
            answers_path=answers,
            samples_path=samples,
            repeat=args.repeat,
            allow_failed_samples=args.allow_failed_samples,
        )
    except GradeInputError as exc:
        parser.error(str(exc))
    env = os.environ.copy()
    api_key = env.get("LLM_API_KEY") or env.get("OPENAI_API_KEY")
    if not api_key:
        parser.error("Set LLM_API_KEY or OPENAI_API_KEY in the environment")
    env.update(
        LLM_API_KEY=api_key,
        LLM_PROVIDER="openai",
        LLM_MODEL_NAME="gpt-5.4",
        CHEAP_LLM_MODEL_NAME="gpt-5-mini",
    )
    command = [
        str(interpreter),
        "-m",
        "src.scripts.answer_evaluation.metrics_based_eval",
        "--questions-file",
        str(questions),
        "--answers-file",
        str(answers),
        "--no-correction",
        "--parallelism",
        str(args.parallelism),
        "--results-file",
        str(result_path),
    ]
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    metadata = {
        "provider": "openai",
        "judge_model": "gpt-5.4",
        "cheap_model": "gpt-5-mini",
        "no_correction": True,
        "benchmark_commit": revision,
        "command": command,
        "questions_sha256": hashlib.sha256(questions.read_bytes()).hexdigest(),
        "answers_sha256": hashlib.sha256(answers.read_bytes()).hexdigest(),
        "samples_sha256": hashlib.sha256(samples.read_bytes()).hexdigest(),
        "allow_failed_samples": args.allow_failed_samples,
        "diagnostic": diagnostic,
        "status": "running",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    result = subprocess.run(command, cwd=repo, env=env, check=False)
    adjusted_status = "not_applicable"
    if diagnostic and result.returncode == 0:
        adjusted_report = build_failure_adjusted_report(
            result_path=result_path,
            selected_questions_path=questions,
            samples_path=samples,
            repeat=args.repeat,
        )
        adjusted_path.write_text(json.dumps(adjusted_report, indent=2) + "\n")
        adjusted_status = "completed"
    metadata.update(
        status="completed" if result.returncode == 0 else "failed",
        exit_code=result.returncode,
        diagnostic_failure_adjusted_path=(
            str(adjusted_path) if diagnostic and result.returncode == 0 else None
        ),
        diagnostic_failure_adjusted_status=adjusted_status,
    )
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
