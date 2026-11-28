"""Small, repeatable turn plans. Timing and chat distributions are assumptions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from mock_llm.code_workload import (
    CodePool,
    Program,
    code_calibration,
    observed_programs,
    tail_programs,
)

ProfileKind = Literal["chat", "search", "research", "held", "code"]


@dataclass(frozen=True)
class TurnProfile:
    kind: ProfileKind
    size: str
    answer_words: int
    search_rounds: int
    queries: int
    reasoning_words: int
    first_output_s: float
    final_duration_s: float
    # Duration of a model call that returns tool calls.
    tool_step_s: float = 1.5
    # Code profile only: the programs that the turn runs, in order.
    programs: tuple[Program, ...] = ()


def stable_number(seed: int, text: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{text}".encode()).digest()[:8], "big")


def profile_kind(model: str) -> ProfileKind | None:
    match = re.search(
        r"(?:^|/)mock-profile-(chat|search|research|held|code)-v1(?:-|$)", model
    )
    if match is None:
        if "mock-profile-" in model:
            raise ValueError("Use mock-profile-{chat,search,research,held,code}-v1")
        return None
    kind = match.group(1)
    if kind == "chat":
        return "chat"
    if kind == "search":
        return "search"
    if kind == "research":
        return "research"
    if kind == "code":
        return "code"
    return "held"


def turn_profile(
    kind: ProfileKind,
    question: str,
    seed: int = 0,
    *,
    code_pool: CodePool = "openai",
    tail_percent: int = 0,
) -> TurnProfile:
    """Correlate longer answers with extra searches; never hash retrieved text.

    A code turn answers like a search turn. Its programs replay one observed
    turn of `code_pool`, or, for `tail_percent` percent of questions, a
    long-tail turn (mock_llm/code_workload.py)."""
    bucket = stable_number(seed, question) % 100
    if bucket < 60:
        size, words, duration = "short", 75, 3.0
    elif bucket < 90:
        size, words, duration = "medium", 180, 4.5
    elif bucket < 95:
        size, words, duration = "long", 900, 12.0
    else:
        size, words, duration = "tail", 1300, 18.0
    rounds = 1 if bucket < 80 else 2 if bucket < 90 else 3 if bucket < 95 else 4
    queries = 3 if bucket >= 90 or bucket in (80, 81) else 1
    reasoning = 60 if stable_number(seed, "reasoning:" + question) % 2 else 0
    if kind == "held":
        return TurnProfile(kind, "held", 600, 0, 1, 0, 1.0, 121.0)
    if kind == "research":
        return TurnProfile(kind, "research", 900, 1, queries, 100, 2.0, 15.0)
    if kind == "code":
        pool = code_calibration()[0]["pools"][code_pool]
        key = f"{seed}:{question}"
        long_tail = stable_number(seed, "tail:" + question) % 100 < tail_percent
        return TurnProfile(
            kind,
            "longtail" if long_tail else size,
            words,
            0,
            pool["queries_per_search"],
            reasoning,
            1.4,
            duration,
            tool_step_s=pool["model_seconds_per_call"],
            programs=tail_programs(key)
            if long_tail
            else observed_programs(key, code_pool),
        )
    return TurnProfile(
        kind,
        size,
        words,
        rounds if kind == "search" else 0,
        queries,
        reasoning,
        1.4,
        duration,
    )


def question_after_label(text: str) -> str | None:
    """Extract the question from Onyx's query-rewrite prompt labels."""
    for label in ("Final user query:", "Final user message:"):
        _, found, tail = text.rpartition(label)
        if found and tail.strip():
            return tail.strip()
    return None


def current_question(text: str) -> str:
    """Match the load client's unpadded question, without truncating long asks."""
    question = question_after_label(text) or text
    return question.split("\nPlease consider the full context", 1)[0].strip()
