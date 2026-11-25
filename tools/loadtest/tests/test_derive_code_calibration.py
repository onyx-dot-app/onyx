"""The calibration derivation over rows in the export query's format
(mock_llm/derive_code_calibration.py docstring)."""

from __future__ import annotations

import json
from typing import Any

from mock_llm.derive_code_calibration import derive, render


def observation(
    session: str,
    row_id: int,
    *,
    run: bool,
    cell: int,
    status: str,
    output_chars: int = 0,
    tools: list[str] | None = None,
    queries: list[int] | None = None,
    seconds: float = 1.0,
) -> dict[str, Any]:
    return {
        "session": session,
        "id": row_id,
        "run": run,
        "cell": cell,
        "status": status,
        "seconds": seconds,
        "output_chars": output_chars,
        "tools": tools or [],
        "queries": queries or [],
    }


OBSERVATIONS = [
    # A program that searched twice and also queried postgres.
    observation(
        "a",
        1,
        run=True,
        cell=1,
        status="completed",
        output_chars=40_053,
        tools=["internal_search", "postgres_query", "internal_search"],
        queries=[3, 1],
    ),
    # A program that ran past its yield time, then a wait observation of it.
    observation(
        "a",
        2,
        run=True,
        cell=2,
        status="running",
        output_chars=1_000,
        tools=["internal_search"],
        queries=[1],
    ),
    observation(
        "a", 3, run=False, cell=2, status="completed", output_chars=800, seconds=2.0
    ),
    observation("a", 4, run=True, cell=3, status="timed_out", seconds=4.0),
    observation("a", 5, run=True, cell=4, status="failed", seconds=0.0),
    observation("b", 6, run=True, cell=1, status="completed", tools=["postgres_query"]),
    # The session of a question that ended with an error.
    observation("c", 7, run=True, cell=1, status="completed", output_chars=5),
]
BENCH = [
    {"chat_session_id": "a", "latency_s": 20.0, "error": None},
    {"chat_session_id": "b", "latency_s": 4.0, "error": None},
    {"chat_session_id": "c", "latency_s": 9.0, "error": "HTTP 500"},
]


def test_observations_fold_into_programs_of_each_turn() -> None:
    result = derive(OBSERVATIONS, [("openai", BENCH)], "fixture")
    pool = result["pools"]["openai"]
    turns = {json.dumps(turn["programs"]): turn["weight"] for turn in pool["turns"]}
    # Output rounds to 500 characters; the wait adds its output to cell 2;
    # timed out and failed cells are failures; only internal_search counts.
    assert turns == {
        json.dumps([[40000, 2, 0], [2000, 1, 0], [0, 0, 1], [0, 0, 1]]): 1,
        json.dumps([[0, 0, 0]]): 1,
    }
    summary = pool["summary"]
    assert (summary["turns"], summary["programs"], summary["waits"]) == (2, 5, 1)
    assert summary["failed_program_share"] == 0.4
    assert pool["queries_per_search"] == 1
    # (20 - 8 program seconds) / 5 calls and (4 - 1) / 2: median of 2.4 and 1.5.
    assert pool["model_seconds_per_call"] == 1.95
    assert result["tail"]["near_cap_output_chars"] == [[40000, 1]]


def test_rendered_file_parses_back_with_one_turn_per_line() -> None:
    result = derive(OBSERVATIONS, [("openai", BENCH)], "fixture")
    text = render(result)
    assert json.loads(text) == result
    assert text.count('{"programs": ') == len(result["pools"]["openai"]["turns"])
