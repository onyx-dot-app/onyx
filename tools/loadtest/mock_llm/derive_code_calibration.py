"""Derive the code mode workload calibration from recorded benchmark chats.

The output, mock_llm/code_calibration.json, holds per-turn program shapes and
aggregate statistics only: no questions, programs, or document content.

Inputs:

- `--calls`: one JSON object per code mode observation, from the saved
  results (`CodeModeExecutionResult`) of the chats' top-level tool calls.
  This query prints them from the Onyx database of the benchmark run. It
  exports no program code or document text; still, keep the file out of the
  repository, because it names chat sessions:

      psql -At -c "SELECT json_build_object(
        'session', chat_session_id, 'id', id,
        'run', tool_call_arguments ? 'code',
        'cell', (result->'details'->>'cell_id')::int,
        'status', result->'details'->>'status',
        'seconds', (result->'details'->>'duration_seconds')::float,
        'output_chars', length(coalesce(result->'details'->>'stdout', '')),
        'tools', (SELECT coalesce(json_agg(c->>'tool_name'), '[]')
          FROM jsonb_array_elements(coalesce(result->'details'->'calls',
          '[]')) c),
        'queries', (SELECT coalesce(json_agg(jsonb_array_length(
          c->'arguments'->'queries')), '[]')
          FROM jsonb_array_elements(coalesce(result->'details'->'calls',
          '[]')) c
          WHERE c->>'tool_name' = 'internal_search'
          AND jsonb_typeof(c->'arguments'->'queries') = 'array'))
        FROM tool_call WHERE parent_chat_message_id IS NOT NULL
        AND result->'details'->>'type' = 'code_mode_execution'"

- `--bench POOL=PATH` (repeatable): a benchmark answers file with one row per
  question (`chat_session_id`, `latency_s`, `error`). POOL names the tool
  family whose turns the file adds to: `openai` or `claude`.

A program is a run call's cell. Its wait observations add their output, run
time, and calls to it, and the last observation gives its status. Output is the
printed text that the model read (the saved stdout, after the server's output
limit). Searches are the program's internal_search calls. A program fails
when its cell ended `failed` or `timed_out`. Questions that ended with an
error are left out.

Runs with the standard library only, so it also runs on the benchmark host.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any

# Program outputs at or above this share of the 40,000-character cap count as
# near the cap.
NEAR_CAP_CHARS = 36_000
# Turns with at least this many programs form the long tail.
TAIL_PROGRAMS = 20
# Output sizes are rounded to this many characters, so turns share templates.
SIZE_STEP = 500
FAILED_STATUSES = ("failed", "timed_out")


@dataclass
class Program:
    output_chars: int = 0
    searches: int = 0
    seconds: float = 0.0
    status: str = ""
    queries: list[int] = field(default_factory=list)

    @property
    def shape(self) -> list[int]:
        return [
            round(self.output_chars / SIZE_STEP) * SIZE_STEP,
            self.searches,
            int(self.status in FAILED_STATUSES),
        ]


@dataclass
class Pool:
    turns: Counter[str] = field(default_factory=Counter)
    programs: list[Program] = field(default_factory=list)
    program_counts: list[int] = field(default_factory=list)
    latency: list[float] = field(default_factory=list)
    model_seconds: list[float] = field(default_factory=list)
    waits: int = 0


def turn_programs(observations: list[dict[str, Any]]) -> tuple[list[Program], int]:
    """A turn's programs in run order, and its wait observations."""
    programs: list[Program] = []
    by_cell: dict[int, Program] = {}
    waits = 0
    for row in sorted(observations, key=lambda row: row["id"]):
        if row["run"]:
            program = Program()
            programs.append(program)
            by_cell[row["cell"]] = program
        elif row["cell"] in by_cell:
            program = by_cell[row["cell"]]
            waits += 1
        else:
            continue
        program.output_chars += row["output_chars"]
        program.searches += row["tools"].count("internal_search")
        program.seconds += row["seconds"] or 0.0
        program.status = row["status"]
        program.queries += row["queries"]
    return programs, waits


def quantile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def histogram(counts: Counter[int]) -> list[list[int]]:
    return [[value, weight] for value, weight in sorted(counts.items())]


def derive(
    observations: list[dict[str, Any]],
    benches: list[tuple[str, list[dict[str, Any]]]],
    source: str,
) -> dict[str, Any]:
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in observations:
        by_session.setdefault(row["session"], []).append(row)

    pools: dict[str, Pool] = {}
    tail_counts: Counter[int] = Counter()
    tail_searches: Counter[int] = Counter()
    near_cap: Counter[int] = Counter()
    for name, rows in benches:
        pool = pools.setdefault(name, Pool())
        for row in rows:
            if row.get("error") or not row.get("latency_s"):
                continue
            programs, waits = turn_programs(by_session.get(row["chat_session_id"], []))
            latency = float(row["latency_s"])
            pool.turns[json.dumps([p.shape for p in programs])] += 1
            pool.programs += programs
            pool.program_counts.append(len(programs))
            pool.latency.append(latency)
            pool.model_seconds.append(
                max(0.0, latency - sum(p.seconds for p in programs))
                / (len(programs) + 1)
            )
            pool.waits += waits
            near_cap.update(
                p.shape[0] for p in programs if p.output_chars >= NEAR_CAP_CHARS
            )
            if len(programs) >= TAIL_PROGRAMS:
                tail_counts[len(programs)] += 1
                tail_searches.update(p.searches for p in programs)

    result: dict[str, Any] = {
        "description": (
            f"{source}. Per-turn program shapes [output_chars, searches, "
            "failed] and aggregates only; no questions, programs, or documents."
        ),
        "near_cap_chars": NEAR_CAP_CHARS,
        "tail_programs": TAIL_PROGRAMS,
        "pools": {},
        "tail": {
            "program_counts": histogram(tail_counts),
            "searches_per_program": histogram(tail_searches),
            "near_cap_output_chars": histogram(near_cap),
        },
    }
    for name, pool in pools.items():
        outputs = [p.output_chars for p in pool.programs]
        counts = pool.program_counts
        result["pools"][name] = {
            "summary": {
                "turns": len(counts),
                "programs": len(outputs),
                "programs_per_turn_mean": round(mean(counts), 2),
                "programs_per_turn_p50": quantile(counts, 0.5),
                "programs_per_turn_p95": quantile(counts, 0.95),
                "programs_per_turn_max": max(counts),
                "tail_turn_share": round(
                    sum(n >= TAIL_PROGRAMS for n in counts) / len(counts), 4
                ),
                "output_chars_mean": round(mean(outputs)),
                "output_chars_p50": quantile(outputs, 0.5),
                "output_chars_p95": quantile(outputs, 0.95),
                "near_cap_share": round(
                    sum(c >= NEAR_CAP_CHARS for c in outputs) / len(outputs), 4
                ),
                "searches_per_program_mean": round(
                    mean(p.searches for p in pool.programs), 2
                ),
                "failed_program_share": round(
                    sum(p.shape[2] for p in pool.programs) / len(outputs), 4
                ),
                "waits": pool.waits,
                "latency_s_p50": quantile(pool.latency, 0.5),
                "latency_s_p95": quantile(pool.latency, 0.95),
                "latency_s_max": max(pool.latency),
            },
            "queries_per_search": round(
                median(q for p in pool.programs for q in p.queries)
            ),
            "model_seconds_per_call": round(median(pool.model_seconds), 2),
            "turns": [
                {"programs": json.loads(shape), "weight": weight}
                for shape, weight in sorted(pool.turns.items())
            ],
        }
    return result


def render(result: dict[str, Any]) -> str:
    """JSON with one turn template per line, so the file stays reviewable."""
    pools = result["pools"]
    text = json.dumps(
        {
            **result,
            "pools": {
                name: {**pool, "turns": f"@turns:{name}@"}
                for name, pool in pools.items()
            },
        },
        indent=2,
    )
    for name, pool in pools.items():
        rows = ",\n".join(
            f'      {{"programs": {json.dumps(turn["programs"], separators=(",", ":"))}, '
            f'"weight": {turn["weight"]}}}'
            for turn in pool["turns"]
        )
        text = text.replace(f'"@turns:{name}@"', "[\n" + rows + "\n    ]")
    return text + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", type=Path, required=True)
    parser.add_argument("--bench", action="append", required=True)
    parser.add_argument("--source", required=True, help="Description of the run")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    observations = [
        json.loads(line) for line in args.calls.read_text().splitlines() if line.strip()
    ]
    benches = []
    for spec in args.bench:
        name, path = spec.split("=", 1)
        rows = [
            json.loads(line)
            for line in Path(path).read_text().splitlines()
            if line.strip()
        ]
        benches.append((name, rows))
    args.output.write_text(render(derive(observations, benches, args.source)))


if __name__ == "__main__":
    main()
