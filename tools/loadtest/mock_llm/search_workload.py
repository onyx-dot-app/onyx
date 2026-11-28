"""Deterministic search helper responses; no production Onyx dependencies."""

from __future__ import annotations

import hashlib
import json
import re
from functools import cache
from pathlib import Path
from typing import Literal, TypedDict, cast


class SelectionTemplate(TypedDict):
    indices: list[int]
    weight: int


class Calibration(TypedDict):
    selection_templates: list[SelectionTemplate]
    classification_labels: dict[str, int]


@cache
def load_calibration() -> tuple[
    list[SelectionTemplate], tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]
]:
    """Load and prepare static fixture data once, when first requested."""
    calibration = cast(
        Calibration,
        json.loads(Path(__file__).with_name("search_calibration.json").read_text()),
    )
    templates = calibration["selection_templates"]
    template_weights = tuple(
        (index, item["weight"]) for index, item in enumerate(templates)
    )
    classifications = tuple(
        (int(value), weight)
        for value, weight in calibration["classification_labels"].items()
    )
    return templates, template_weights, classifications


def sample_histogram(text: str, histogram: tuple[tuple[int, int], ...]) -> int:
    """Stable sampling across processes, transports, and repeated requests."""
    bucket = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    bucket %= sum(weight for _, weight in histogram)
    for value, weight in histogram:
        if bucket < weight:
            return value
        bucket -= weight
    raise AssertionError("Invalid histogram")


HelperKind = Literal[
    "selection", "classification", "source", "time", "keyword", "semantic"
]


def helper_kind(prompt: str, system: str = "") -> HelperKind | None:
    if prompt.startswith("Select the most relevant document sections for the user"):
        return "selection"
    if prompt.startswith(
        "Analyze the relevance of document sections to a search query and classify"
    ):
        return "classification"
    if prompt.startswith("You scope an internal search to its relevant sources."):
        return "source"
    if prompt.startswith("You scope an internal search to a time filter,"):
        return "time"
    if "reformulates the last user message" in system:
        return "keyword" if "standalone keyword queries" in system else "semantic"
    return None


def helper_duration(prompt: str, system: str) -> float | None:
    durations: dict[HelperKind, float] = {
        "selection": 1.04,
        "classification": 0.88,
        "source": 1.0,
        "time": 1.0,  # Uncalibrated scope calls.
        "keyword": 1.15,
        "semantic": 0.99,
    }
    kind = helper_kind(prompt, system)
    return durations[kind] if kind is not None else None


def search_helper_answer(
    prompt: str, *, selected_count: int | None = None, classification: int | None = None
) -> str | None:
    """Recognize full prompt contracts, not document text that quotes one phrase."""
    kind = helper_kind(prompt)
    if kind == "selection":
        match = re.search(
            r"# Document Sections\s*```\s*(.*?)\n```\s*# User Query", prompt, re.DOTALL
        )
        limit = re.search(r"\(maximum (\d+)\)", prompt)
        if match is None or limit is None:
            raise ValueError("Unsupported document selection prompt")
        sections = json.loads(match.group(1))
        ids = list(dict.fromkeys(section["section_id"] for section in sections))
        templates, template_weights, _ = load_calibration()
        template = templates[sample_histogram(prompt, template_weights)]["indices"]
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
    if kind == "classification":
        value = (
            classification
            if classification is not None
            else sample_histogram(prompt, load_calibration()[2])
        )
        return str(value)
    if kind == "source":
        # Unscoped ERAG workload: valid empty scope, never an invented source.
        return "[]"
    if kind == "time":
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
