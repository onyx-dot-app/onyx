"""Code mode turn plans sampled from recorded benchmark chats.

code_calibration.json (written by derive_code_calibration.py) holds the
observed turns of each tool family's pool as ordered programs. A plan replays
one observed turn, or a long-tail turn built from the observed tail.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict, cast

from mock_llm.search_workload import sample_histogram

# The tool family whose observed turns a plan replays. Onyx gives a model the
# Claude tool shapes when its name contains "claude", so the mock does too.
CodePool = Literal["openai", "claude"]


class Program(NamedTuple):
    # Characters the program prints, before the server's output limit.
    output_chars: int
    # internal_search calls the program makes.
    searches: int
    # The program ends with an error, as observed for that program.
    failed: bool


class TurnTemplate(TypedDict):
    programs: list[list[int]]
    weight: int


class PoolCalibration(TypedDict):
    summary: dict[str, float]
    queries_per_search: int
    model_seconds_per_call: float
    turns: list[TurnTemplate]


class TailCalibration(TypedDict):
    program_counts: list[list[int]]
    searches_per_program: list[list[int]]
    near_cap_output_chars: list[list[int]]


class CodeCalibration(TypedDict):
    pools: dict[str, PoolCalibration]
    tail: TailCalibration


class Histograms(NamedTuple):
    turns: dict[str, tuple[tuple[int, int], ...]]
    tail_counts: tuple[tuple[int, int], ...]
    tail_searches: tuple[tuple[int, int], ...]
    tail_outputs: tuple[tuple[int, int], ...]


@cache
def code_calibration() -> tuple[CodeCalibration, Histograms]:
    """Load the fixture and its sampling weights once, when first requested."""
    calibration = cast(
        CodeCalibration,
        json.loads(Path(__file__).with_name("code_calibration.json").read_text()),
    )
    tail = calibration["tail"]
    return calibration, Histograms(
        turns={
            name: tuple(
                (index, turn["weight"]) for index, turn in enumerate(pool["turns"])
            )
            for name, pool in calibration["pools"].items()
        },
        tail_counts=tuple((value, weight) for value, weight in tail["program_counts"]),
        tail_searches=tuple(
            (value, weight) for value, weight in tail["searches_per_program"]
        ),
        tail_outputs=tuple(
            (value, weight) for value, weight in tail["near_cap_output_chars"]
        ),
    )


def observed_programs(key: str, pool: CodePool) -> tuple[Program, ...]:
    """One observed turn of the pool, chosen by its observed weight."""
    calibration, histograms = code_calibration()
    turn = calibration["pools"][pool]["turns"][
        sample_histogram(f"{key}:turn", histograms.turns[pool])
    ]
    return tuple(
        Program(output_chars, searches, bool(failed))
        for output_chars, searches, failed in turn["programs"]
    )


def tail_programs(key: str) -> tuple[Program, ...]:
    """A long-tail turn: a program count of the observed tail turns, and each
    program's output and searches from the observed near-cap outputs and
    tail programs. Tail plans have no failed programs."""
    _, histograms = code_calibration()
    count = sample_histogram(f"{key}:tail", histograms.tail_counts)
    return tuple(
        Program(
            sample_histogram(f"{key}:output:{index}", histograms.tail_outputs),
            sample_histogram(f"{key}:searches:{index}", histograms.tail_searches),
            False,
        )
        for index in range(count)
    )
