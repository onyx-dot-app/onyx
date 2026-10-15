"""Validate swarm outputs against the brief's contract and print a summary table.

Checks each swarm/out/<slice>/rules.json (or anti_rules.json): required fields, source
ids exist in the slice, excerpts are verbatim substrings of the cited row, severity and
confidence enums. Writes swarm/merged/all_rules.json and swarm/merged/all_anti_rules.json
with a `slice` field on every rule, dropping nothing (problems are reported, not
silently fixed).

Usage: validate_rules.py [--workdir DIR]"""

import json
import sys
from pathlib import Path

from common import parse_workdir

RULE_FIELDS = {
    "id",
    "title",
    "statement",
    "rationale",
    "scope_globs",
    "severity",
    "reviewers",
    "source_threads",
    "single_source",
    "contested",
    "overlaps_existing",
    "positive_examples",
    "negative_examples",
    "jev_question",
    "llm_guidance",
    "confidence",
}
ANTI_FIELDS = {
    "id",
    "bot_pattern",
    "why_dismissed",
    "codebase_fact",
    "linter_behaviour",
    "reviewers",
    "source_threads",
    "examples",
    "confidence",
}
SEVERITIES = {"nit", "should_fix", "must_fix"}
CONFIDENCES = {"high", "medium", "low"}


def load_slice(slices: Path, name: str) -> dict[int, dict]:
    rows = {}
    for line in (slices / f"{name}.jsonl").open():
        r = json.loads(line)
        rows[r["id"]] = r
    return rows


def verbatim(excerpt: str, row: dict, fields: tuple[str, ...]) -> bool:
    if not excerpt:
        return True
    return any(excerpt in (row.get(f) or "") for f in fields)


def check_rule(rule: dict, rows: dict[int, dict], anti: bool) -> list[str]:
    problems = []
    missing = (ANTI_FIELDS if anti else RULE_FIELDS) - set(rule)
    if missing:
        problems.append(f"missing fields {sorted(missing)}")
    problems.extend(
        f"source thread {tid} not in slice"
        for tid in rule.get("source_threads", [])
        if tid not in rows
    )
    if not anti and rule.get("severity") not in SEVERITIES:
        problems.append(f"bad severity {rule.get('severity')!r}")
    if rule.get("confidence") not in CONFIDENCES:
        problems.append(f"bad confidence {rule.get('confidence')!r}")
    ex_key = "examples" if anti else "positive_examples"
    for ex in rule.get(ex_key, []) + (
        [] if anti else rule.get("negative_examples", [])
    ):
        row = rows.get(ex.get("thread_id"))
        if row is None:
            problems.append(f"example thread {ex.get('thread_id')} not in slice")
            continue
        if not verbatim(ex.get("hunk_excerpt", ""), row, ("diff_hunk",)):
            problems.append(f"hunk excerpt not verbatim for {ex['thread_id']}")
        if not verbatim(ex.get("comment_excerpt", ""), row, ("body",)):
            problems.append(f"comment excerpt not verbatim for {ex['thread_id']}")
        if anti:
            if not verbatim(ex.get("bot_excerpt", ""), row, ("bot_comment",)):
                problems.append(f"bot excerpt not verbatim for {ex['thread_id']}")
            if not verbatim(ex.get("reply_excerpt", ""), row, ("body",)):
                problems.append(f"reply excerpt not verbatim for {ex['thread_id']}")
    if not anti:
        q = rule.get("jev_question", {})
        if (
            not q.get("instructions")
            or "true" not in q.get("criteria", {})
            or "false" not in q.get("criteria", {})
        ):
            problems.append("jev_question incomplete")
    return problems


def main() -> None:
    swarm = parse_workdir(__doc__) / "swarm"
    slices = swarm / "slices"
    merged = swarm / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    all_rules, all_anti = [], []
    print(f"{'slice':26s} {'rows':>5s} {'rules':>5s} {'ok':>3s} {'bad':>3s}  report")
    for d in sorted((swarm / "out").iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        anti = name.startswith("bot-pushback")
        f = d / ("anti_rules.json" if anti else "rules.json")
        if not f.exists():
            print(
                f"{name:26s} {'-':>5s} {'-':>5s} {'-':>3s} {'-':>3s}  MISSING {f.name}"
            )
            continue
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            print(f"{name:26s} INVALID JSON: {e}")
            continue
        rows = load_slice(slices, name)
        rules = data.get("anti_rules" if anti else "rules", [])
        ok = bad = 0
        for rule in rules:
            rule["slice"] = name
            probs = check_rule(rule, rows, anti)
            rule["validation_problems"] = probs
            if probs:
                bad += 1
                print(f"    {rule.get('id')}: {'; '.join(probs)[:200]}")
            else:
                ok += 1
            (all_anti if anti else all_rules).append(rule)
        report = (
            (d / "REPORT.md").read_text().strip().splitlines()[-1][:60]
            if (d / "REPORT.md").exists()
            else "no REPORT.md"
        )
        print(
            f"{name:26s} {data.get('rows_read', '?'):>5} {len(rules):>5d} {ok:>3d} {bad:>3d}  {report}"
        )
    (merged / "all_rules.json").write_text(json.dumps(all_rules, indent=1))
    (merged / "all_anti_rules.json").write_text(json.dumps(all_anti, indent=1))
    print(f"\nmerged {len(all_rules)} rules, {len(all_anti)} anti-rules -> {merged}")


if __name__ == "__main__":
    sys.exit(main())
