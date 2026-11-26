"""The calibration derivation over rows in the export query's format
(mock_llm/derive_code_calibration.py docstring)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mock_llm.derive_code_calibration import TAIL_PROGRAMS, derive, render


def observation(
    session: str,
    row_id: int,
    *,
    run: bool,
    cell: int,
    status: str,
    output_chars: int = 0,
    calls: list[tuple[int, str, int | None]] | None = None,
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
        "calls": calls or [],
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
        calls=[(0, "internal_search", 3), (1, "postgres_query", None)]
        + [(2, "internal_search", 1)],
    ),
    # A program that ran past its yield time with a search still running, then
    # a wait observation that reports the same search again when it ended.
    # Run time is cumulative: the program ran 2 seconds in all.
    observation(
        "a",
        2,
        run=True,
        cell=2,
        status="running",
        output_chars=1_000,
        calls=[(0, "internal_search", 1)],
    ),
    observation(
        "a",
        3,
        run=False,
        cell=2,
        status="completed",
        output_chars=800,
        calls=[(0, "internal_search", 1)],
        seconds=2.0,
    ),
    observation("a", 4, run=True, cell=3, status="timed_out", seconds=4.0),
    observation("a", 5, run=True, cell=4, status="failed", seconds=0.0),
    observation(
        "b",
        6,
        run=True,
        cell=1,
        status="completed",
        calls=[(0, "postgres_query", None)],
    ),
    # The session of a question that ended with an error.
    observation("c", 7, run=True, cell=1, status="completed", output_chars=5),
]
# A long-tail turn: TAIL_PROGRAMS programs that each search once.
TAIL = [
    observation(
        "d",
        100 + cell,
        run=True,
        cell=cell,
        status="completed",
        output_chars=36_000,
        calls=[(0, "internal_search", 2)],
        seconds=0.5,
    )
    for cell in range(TAIL_PROGRAMS)
]
BENCH = [
    {"chat_session_id": "a", "latency_s": 20.0, "error": None},
    {"chat_session_id": "b", "latency_s": 4.0, "error": None},
    {"chat_session_id": "c", "latency_s": 9.0, "error": "HTTP 500"},
]
TAIL_BENCH = [{"chat_session_id": "d", "latency_s": 31.0, "error": None}]


def test_observations_fold_into_programs_of_each_turn() -> None:
    result = derive(
        OBSERVATIONS + TAIL, [("openai", BENCH), ("claude", TAIL_BENCH)], "fixture"
    )
    pool = result["pools"]["openai"]
    turns = {json.dumps(turn["programs"]): turn["weight"] for turn in pool["turns"]}
    # Output rounds to 500 characters; the wait adds its output to cell 2, and
    # its search counts once; timed out and failed cells are failures; only
    # internal_search counts.
    assert turns == {
        json.dumps([[40000, 2, 0], [2000, 1, 0], [0, 0, 1], [0, 0, 1]]): 1,
        json.dumps([[0, 0, 0]]): 1,
    }
    summary = pool["summary"]
    assert (summary["turns"], summary["programs"], summary["waits"]) == (2, 5, 1)
    assert summary["failed_program_share"] == 0.4
    assert pool["queries_per_search"] == 1
    # (20 - 7 program seconds) / 5 calls and (4 - 1) / 2: median of 2.6 and 1.5.
    assert pool["model_seconds_per_call"] == 2.05
    assert result["tail"] == {
        "program_counts": [[TAIL_PROGRAMS, 1]],
        "searches_per_program": [[1, TAIL_PROGRAMS]],
        "near_cap_output_chars": [[36000, TAIL_PROGRAMS], [40000, 1]],
    }
    claude = result["pools"]["claude"]
    assert claude["queries_per_search"] == 2
    assert claude["summary"]["tail_turn_share"] == 1


def test_pool_without_searches_gets_one_query_per_search() -> None:
    bench = [*BENCH, *TAIL_BENCH]
    rows = [
        {**row, "calls": [c for c in row["calls"] if c[1] != "internal_search"]}
        for row in OBSERVATIONS + TAIL
    ]
    assert (
        derive(rows, [("openai", bench)], "fixture")["pools"]["openai"][
            "queries_per_search"
        ]
        == 1
    )


def test_calibration_without_a_long_tail_is_rejected() -> None:
    with pytest.raises(ValueError, match="tail plans need both"):
        derive(OBSERVATIONS, [("openai", BENCH)], "fixture")


def test_rendered_file_parses_back_with_one_turn_per_line() -> None:
    result = derive(OBSERVATIONS + TAIL, [("openai", BENCH + TAIL_BENCH)], "fixture")
    text = render(result)
    assert json.loads(text) == result
    assert text.count('{"programs": ') == len(result["pools"]["openai"]["turns"])
