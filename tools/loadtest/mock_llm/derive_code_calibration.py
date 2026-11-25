"""Derive the code mode workload calibration from recorded benchmark chats.

The output, mock_llm/code_calibration.json, holds per-turn program shapes and
aggregate statistics only: no questions, programs, or document content.

Inputs:

- `--calls`: the chats' top-level tool calls, one JSON object per line, as
  this query prints them from the Onyx database of the benchmark run:

      psql -At -c "SELECT json_build_object('session', chat_session_id,
        'id', id, 'arguments', tool_call_arguments,
        'content', result->>'content')
        FROM tool_call WHERE parent_chat_message_id IS NOT NULL"

- `--bench POOL=PATH` (repeatable): a benchmark answers file with one row per
  question (`chat_session_id`, `latency_s`, `error`). POOL names the tool
  family whose turns the file adds to: `openai` or `claude`.

Each turn is the ordered list of its run calls (calls with a `code` argument).
A program's output is the text after `Output:` in its result, which the
server already cut to its output limit. Its searches are the tool calls its
result header reports, when the program calls `internal_search`. Questions
that ended with an error are left out.

Runs with the standard library only, so it also runs on the benchmark host.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean, median

_HEADER_RE = re.compile(
    r"^Execution (\w[\w ]*?) in cell \d+ in ([\d.]+)s with (\d+) tool calls?\."
)
_OUTPUT_RE = re.compile(r"\n\nOutput:\n(.*?)(?:\n\nError:\n|\Z)", re.DOTALL)
# Program outputs at or above this share of the 40,000-character cap count as
# near the cap.
NEAR_CAP_CHARS = 36_000
# Turns with at least this many programs form the long tail.
TAIL_PROGRAMS = 20
# Output sizes are rounded to this many characters, so turns share templates.
SIZE_STEP = 500


def quantile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def query_counts(code: str) -> list[int]:
    """Query counts of the literal `queries=[...]` lists of internal_search calls."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return [
        len(keyword.value.elts)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "internal_search"
        for keyword in node.keywords
        if keyword.arg == "queries" and isinstance(keyword.value, ast.List)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=Path, required=True)
    parser.add_argument("--bench", action="append", required=True)
    parser.add_argument("--source", required=True, help="Description of the run")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    calls: dict[str, list[tuple[int, dict, str]]] = {}
    for line in args.calls.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            calls.setdefault(row["session"], []).append(
                (row["id"], row["arguments"] or {}, row["content"] or "")
            )

    pools: dict[str, dict] = {}
    tail_counts: Counter[int] = Counter()
    tail_searches: Counter[int] = Counter()
    near_cap: Counter[int] = Counter()
    for spec in args.bench:
        pool_name, path = spec.split("=", 1)
        pool = pools.setdefault(
            pool_name,
            {
                "turns": Counter(),
                "latency": [],
                "model_seconds": [],
                "queries": [],
                "programs": [],
                "outputs": [],
                "searches": [],
                "failed": 0,
                "waits": 0,
            },
        )
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("error") or not row.get("latency_s"):
                continue
            turn: list[tuple[int, int, int]] = []
            program_seconds = 0.0
            ordered = sorted(calls.get(row["chat_session_id"], []))
            for _, arguments, content in ordered:
                if "code" not in arguments:
                    pool["waits"] += "cell_id" in arguments
                    continue
                header = _HEADER_RE.match(content)
                if header is None:
                    continue
                status, seconds, tool_calls = header.groups()
                program_seconds += float(seconds)
                output = _OUTPUT_RE.search(content)
                chars = len(output.group(1)) if output else 0
                searches = (
                    int(tool_calls) if "internal_search" in arguments["code"] else 0
                )
                failed = int(status == "failed")
                turn.append((round(chars / SIZE_STEP) * SIZE_STEP, searches, failed))
                pool["outputs"].append(chars)
                pool["searches"].append(searches)
                pool["failed"] += failed
                pool["queries"].extend(query_counts(arguments["code"]))
                if chars >= NEAR_CAP_CHARS:
                    near_cap[round(chars / SIZE_STEP) * SIZE_STEP] += 1
            pool["turns"][json.dumps(turn)] += 1
            pool["programs"].append(len(turn))
            pool["latency"].append(float(row["latency_s"]))
            pool["model_seconds"].append(
                max(0.0, float(row["latency_s"]) - program_seconds) / (len(turn) + 1)
            )
            if len(turn) >= TAIL_PROGRAMS:
                tail_counts[len(turn)] += 1
                tail_searches.update(searches for _, searches, _ in turn)

    result = {
        "description": (
            f"{args.source}. Per-turn program shapes [output_chars, searches, "
            "failed] and aggregates only; no questions, programs, or documents."
        ),
        "near_cap_chars": NEAR_CAP_CHARS,
        "tail_programs": TAIL_PROGRAMS,
        "pools": {},
        "tail": {
            "program_counts": [[n, w] for n, w in sorted(tail_counts.items())],
            "searches_per_program": [[n, w] for n, w in sorted(tail_searches.items())],
            "near_cap_output_chars": [[n, w] for n, w in sorted(near_cap.items())],
        },
    }
    for name, pool in pools.items():
        outputs = pool["outputs"]
        programs = pool["programs"]
        result["pools"][name] = {
            "summary": {
                "turns": len(programs),
                "programs": len(outputs),
                "programs_per_turn_mean": round(mean(programs), 2),
                "programs_per_turn_p50": quantile(programs, 0.5),
                "programs_per_turn_p95": quantile(programs, 0.95),
                "programs_per_turn_max": max(programs),
                "tail_turn_share": round(
                    sum(n >= TAIL_PROGRAMS for n in programs) / len(programs), 4
                ),
                "output_chars_mean": round(mean(outputs)),
                "output_chars_p50": quantile(outputs, 0.5),
                "output_chars_p95": quantile(outputs, 0.95),
                "near_cap_share": round(
                    sum(c >= NEAR_CAP_CHARS for c in outputs) / len(outputs), 4
                ),
                "searches_per_program_mean": round(mean(pool["searches"]), 2),
                "failed_program_share": round(pool["failed"] / len(outputs), 4),
                "waits": pool["waits"],
                "latency_s_p50": quantile(pool["latency"], 0.5),
                "latency_s_p95": quantile(pool["latency"], 0.95),
                "latency_s_max": max(pool["latency"]),
            },
            "queries_per_search": round(median(pool["queries"])),
            "model_seconds_per_call": round(median(pool["model_seconds"]), 2),
            "turns": f"@turns:{name}@",
        }
    # One turn template per line keeps the file reviewable.
    text = json.dumps(result, indent=2)
    for name, pool in pools.items():
        rows = ",\n".join(
            f'      {{"programs": {shape.replace(" ", "")}, "weight": {weight}}}'
            for shape, weight in sorted(pool["turns"].items())
        )
        text = text.replace(f'"@turns:{name}@"', "[\n" + rows + "\n    ]")
    args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
