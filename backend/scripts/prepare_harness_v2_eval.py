"""Freeze a balanced question subset or export completed answers for ERAG grading."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")


def select_questions(
    rows: list[dict[str, Any]], per_type: int, seed: str
) -> list[dict[str, Any]]:
    ids = [r["question_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate source question IDs")
    if per_type < 1:
        raise ValueError("per_type must be positive")

    def rank(row: dict[str, Any]) -> str:
        return hashlib.sha256((seed + ":" + row["question_id"]).encode()).hexdigest()

    selected = []
    for kind in sorted({r["question_type"] for r in rows}):
        candidates = sorted((r for r in rows if r["question_type"] == kind), key=rank)
        if len(candidates) < per_type:
            raise ValueError("Insufficient questions for type: " + kind)
        selected.extend(candidates[:per_type])
    return sorted(selected, key=rank)


def cited_documents(row: dict[str, Any]) -> tuple[list[str], list[int]]:
    raw = row.get("raw", {})
    if row["variant"] == "v2":
        mapping = raw.get("result", {}).get("citation_mapping", {})
    else:
        mapping = {
            str(c["citation_number"]): c["document_id"]
            for c in raw.get("citation_info", [])
        }
    numbers = list(
        dict.fromkeys(
            int(number.strip())
            for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", row.get("answer", ""))
            for number in group.split(",")
        )
    )
    docs = list(dict.fromkeys(mapping[str(n)] for n in numbers if str(n) in mapping))
    return docs, [n for n in numbers if str(n) not in mapping]


def export_variant(
    questions: list[dict[str, Any]], results: list[dict[str, Any]], variant: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = [r for r in results if r["variant"] == variant]
    by_id = {r["question_id"]: r for r in selected}
    expected = {q["question_id"] for q in questions}
    if len(by_id) != len(selected) or set(by_id) != expected:
        raise ValueError("Expected exactly one result per question and variant")
    answers, samples = [], []
    for question in questions:
        row = by_id[question["question_id"]]
        if row["question"] != question["question"]:
            raise ValueError("Question text changed")
        docs, unresolved = cited_documents(row)
        succeeded = row["outcome"] == "completed" and bool(
            row.get("answer", "").strip()
        )
        answer = row["answer"] if succeeded else ""
        document_ids = docs if succeeded else []
        exported = {
            "question_id": row["question_id"],
            "answer": answer,
            "document_ids": document_ids,
            "document_id_semantics": "cited",
        }
        answers.append(exported)
        samples.append(
            {
                **exported,
                "repeat_index": 1,
                "status": "succeeded" if succeeded else "failed",
                "harness_outcome": row["outcome"],
                "raw_answer": row.get("answer", ""),
                "raw_cited_document_ids": docs,
                "unresolved_citation_numbers": unresolved,
                "client_total_ms": row["client_total_ms"],
            }
        )
    return answers, samples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("select")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--per-type", type=int, default=2)
    prepare.add_argument("--seed", default="harness-v2-pilot-01")
    prepare.add_argument("--question-ids")
    export = commands.add_parser("export")
    export.add_argument("--questions", type=Path, required=True)
    export.add_argument("--results", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--variant", choices=["both", "legacy", "v2"], default="both")
    merge = commands.add_parser("merge")
    merge.add_argument("--baseline-results", type=Path, required=True)
    merge.add_argument("--candidate-results", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "merge":
        controls = [
            r for r in read_rows(args.baseline_results) if r["variant"] == "legacy"
        ]
        candidates = read_rows(args.candidate_results)
        if not controls or not candidates:
            raise ValueError("Both variants must contain results")
        if any(r["variant"] != "v2" for r in candidates):
            raise ValueError("Candidate file must contain only v2 results")
        questions = [{k: r[k] for k in ("question_id", "question")} for r in controls]
        combined = controls + candidates
        for variant in ("legacy", "v2"):
            export_variant(questions, combined, variant)
        write_rows(args.output, combined)
        return
    if args.command == "select":
        source_rows = read_rows(args.source)
        if args.question_ids:
            ids = args.question_ids.split(",")
            by_id = {r["question_id"]: r for r in source_rows}
            if (
                len(by_id) != len(source_rows)
                or len(set(ids)) != len(ids)
                or not set(ids) <= set(by_id)
            ):
                raise ValueError("Explicit question IDs must be unique and present")
            rows = [by_id[q] for q in ids]
        else:
            rows = select_questions(source_rows, args.per_type, args.seed)
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        write_rows(args.output / "selected_questions.jsonl", rows)
        write_rows(
            args.output / "questions.jsonl",
            [{k: r[k] for k in ("question_id", "question")} for r in rows],
        )
        manifest = {
            "seed": None if args.question_ids else args.seed,
            "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
            "question_ids": [r["question_id"] for r in rows],
            "question_types": {r["question_id"]: r["question_type"] for r in rows},
            "selection_uses_answers_or_scores": None if args.question_ids else False,
            "selection_method": "explicit_ids"
            if args.question_ids
            else "stratified_hash",
        }
        (args.output / "selection.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    else:
        questions, results = read_rows(args.questions), read_rows(args.results)
        exported = {
            variant: export_variant(questions, results, variant)
            for variant in (
                ("legacy", "v2") if args.variant == "both" else (args.variant,)
            )
        }
        args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        for variant, (answers, samples) in exported.items():
            target = args.output / variant
            target.mkdir(mode=0o700)
            write_rows(target / "selected_questions.jsonl", questions)
            write_rows(target / "answers_repeat_01.jsonl", answers)
            write_rows(target / "samples.jsonl", samples)


if __name__ == "__main__":
    main()
