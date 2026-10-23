"""Deterministic search helper responses; no production Onyx dependencies."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import TypedDict, cast


class SelectionTemplate(TypedDict):
    indices: list[int]
    weight: int


class Calibration(TypedDict):
    selection_templates: list[SelectionTemplate]
    classification_labels: dict[str, int]


_CALIBRATION = cast(
    Calibration,
    json.loads(Path(__file__).with_name("search_calibration.json").read_text()),
)
_TEMPLATES = _CALIBRATION["selection_templates"]
_TEMPLATE_WEIGHTS = tuple(
    (index, item["weight"]) for index, item in enumerate(_TEMPLATES)
)
CLASSIFICATIONS = tuple(
    (int(value), weight)
    for value, weight in _CALIBRATION["classification_labels"].items()
)


def sample_histogram(text: str, histogram: tuple[tuple[int, int], ...]) -> int:
    """Stable sampling across processes, transports, and repeated requests."""
    bucket = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    bucket %= sum(weight for _, weight in histogram)
    for value, weight in histogram:
        if bucket < weight:
            return value
        bucket -= weight
    raise AssertionError("Invalid histogram")


def search_helper_answer(
    prompt: str, *, selected_count: int | None = None, classification: int | None = None
) -> str | None:
    """Recognize full prompt contracts, not document text that quotes one phrase."""
    if prompt.startswith("Select the most relevant document sections for the user"):
        match = re.search(
            r"# Document Sections\s*```\s*(.*?)\n```\s*# User Query", prompt, re.DOTALL
        )
        limit = re.search(r"\(maximum (\d+)\)", prompt)
        if match is None or limit is None:
            raise ValueError("Unsupported document selection prompt")
        sections = json.loads(match.group(1))
        ids = list(dict.fromkeys(section["section_id"] for section in sections))
        template = _TEMPLATES[sample_histogram(prompt, _TEMPLATE_WEIGHTS)]["indices"]
        count = selected_count if selected_count is not None else len(template)
        ranks = list(
            dict.fromkeys(
                [index for index in template if index < len(ids)]
                + list(range(len(ids)))
            )
        )
        return json.dumps(
            [ids[index] for index in ranks[: min(count, int(limit.group(1)))]]
        )
    if prompt.startswith(
        "Analyze the relevance of document sections to a search query and classify"
    ):
        value = (
            classification
            if classification is not None
            else sample_histogram(prompt, CLASSIFICATIONS)
        )
        return str(value)
    if prompt.startswith("You scope an internal search to its relevant sources."):
        # Unscoped ERAG workload: valid empty scope, never an invented source.
        return "[]"
    if prompt.startswith("You scope an internal search to a time filter,"):
        return "updated (None, None)"
    return None


def keyword_query(query: str) -> str:
    """Keep query-specific terms without padding or fabricated expansions."""
    stop_words = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "what",
        "which",
        "who",
        "how",
        "does",
        "do",
        "can",
        "could",
        "please",
        "tell",
        "me",
        "about",
        "of",
        "for",
        "to",
        "in",
        "and",
    }
    terms = re.findall(r"[\w]+(?:[-'][\w]+)*", query)
    return " ".join(term for term in terms if term.lower() not in stop_words) or query
