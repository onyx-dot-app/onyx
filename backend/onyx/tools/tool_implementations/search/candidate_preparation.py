"""Bounded candidate breadth and faithful query-focused excerpts; no model calls."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from onyx.context.search.models import InferenceSection


def distinct_document_sections(
    sections: list[InferenceSection], limit: int = 200
) -> list[InferenceSection]:
    seen: set[str] = set()
    result = []
    for section in sections:
        doc = section.center_chunk.document_id
        if doc in seen:
            continue
        seen.add(doc)
        result.append(section)
        if len(result) == limit:
            break
    return result


def focused_excerpt(text: str, query: str, chars: int) -> str:
    if len(text) <= chars:
        return text
    terms = set(re.findall(r"[\w.-]{3,}", query.casefold()))
    # Overlapping windows retain exact source text; select by distinct query-term overlap.
    width = max(80, min(500, chars))
    windows = [
        (i, text[i : i + width]) for i in range(0, len(text), max(40, width // 2))
    ]
    ranked = sorted(
        windows,
        key=lambda w: (
            -len(terms & set(re.findall(r"[\w.-]{3,}", w[1].casefold()))),
            w[0],
        ),
    )
    chosen: list[tuple[int, str]] = []
    remaining = chars
    for offset, content in ranked:
        if any(abs(offset - prior) < width for prior, _ in chosen):
            continue
        take = min(len(content), remaining - (5 if chosen else 0))
        if take <= 0:
            break
        chosen.append((offset, content[:take]))
        remaining -= take + (5 if len(chosen) > 1 else 0)
        if remaining < 80:
            break
    return " ... ".join(content for _, content in sorted(chosen))[:chars]


def bounded_selection_prompt(
    cards: list[dict[str, Any]],
    query: str,
    render: Callable[[str], str],
    count_tokens: Callable[[str], int],
    budget: int,
) -> tuple[str, dict[str, Any]]:
    """Fit the complete rendered prompt, including metadata and instructions.

    Shrink all candidate excerpts before omitting any document. Omission is
    explicit and occurs only if even tiny cards exceed the input budget.
    """
    originals = [
        {
            "section_id": c["section_id"],
            "title": re.sub(r"[0-9a-fA-F]{24,}", "", str(c["title"]))[:160],
            "source_type": c.get("source_type", ""),
            "content": c["content"],
        }
        for c in cards
    ]
    included = list(originals)
    chars = 1600
    rounds = 0
    while True:
        rounds += 1
        compact = [
            {
                **c,
                "content": focused_excerpt(
                    c["content"], query, min(1600, chars * (3 if i < 20 else 1))
                ),
            }
            for i, c in enumerate(included)
        ]
        prompt = render(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
        tokens = count_tokens(prompt)
        if tokens <= budget:
            return prompt, {
                "input_tokens": tokens,
                "input_token_budget": budget,
                "candidate_count": len(cards),
                "included_section_ids": [c["section_id"] for c in compact],
                "omitted_section_ids": [
                    c["section_id"] for c in originals[len(included) :]
                ],
                "excerpt_chars": chars,
                "priority_excerpt_chars": min(1600, chars * 3),
                "priority_candidate_count": min(20, len(included)),
                "fit_rounds": rounds,
            }
        if chars > 80:
            chars = max(80, min(chars - 1, int(chars * budget / tokens * 0.85)))
        elif included:
            included = included[
                : max(
                    0,
                    min(len(included) - 1, int(len(included) * budget / tokens * 0.85)),
                )
            ]
        else:
            raise ValueError(
                "Selection instructions alone exceed the input token budget"
            )
