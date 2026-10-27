"""Small, repeatable turn plans. Timing and chat distributions are assumptions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

ProfileKind = Literal["chat", "search", "research", "held"]


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


def stable_number(seed: int, text: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{text}".encode()).digest()[:8], "big")


def profile_kind(model: str) -> ProfileKind | None:
    match = re.search(
        r"(?:^|/)mock-profile-(chat|search|research|held)-v1(?:-|$)", model
    )
    if match is None:
        if "mock-profile-" in model:
            raise ValueError("Use mock-profile-{chat,search,research,held}-v1")
        return None
    kind = match.group(1)
    if kind == "chat":
        return "chat"
    if kind == "search":
        return "search"
    if kind == "research":
        return "research"
    return "held"


def turn_profile(kind: ProfileKind, question: str, seed: int = 0) -> TurnProfile:
    """Correlate longer answers with extra searches; never hash retrieved text."""
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
