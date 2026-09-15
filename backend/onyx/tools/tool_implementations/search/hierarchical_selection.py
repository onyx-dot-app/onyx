"""Bounded query-wise candidate selection for noisy multi-query retrieval."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from onyx.context.search.models import InferenceChunk, InferenceSection
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion
from onyx.tools.tool_implementations.search.search_utils import (
    expand_section_with_context,
)
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _distinct_document_sections(
    chunks: list[InferenceChunk], candidate_limit: int
) -> list[InferenceSection]:
    sections = merge_individual_chunks(chunks[:candidate_limit])
    seen: set[str] = set()
    distinct: list[InferenceSection] = []
    for section in sections:
        document_id = section.center_chunk.document_id
        if document_id in seen:
            continue
        seen.add(document_id)
        distinct.append(section)
    return distinct


def select_hierarchically(
    *,
    ranked_results: list[list[InferenceChunk]],
    user_query: str,
    llm: LLM,
    document_index: Any,
    candidate_limit_per_query: int = 100,
    winners_per_query: int = 10,
    final_limit: int = 10,
    selector: Callable[
        ..., tuple[list[InferenceSection], list[str] | None]
    ] = select_sections_for_expansion,
    expander: Callable[..., InferenceSection | None] = expand_section_with_context,
) -> tuple[list[InferenceSection], list[str] | None, dict[str, Any]]:
    """Nominate per query, then compare the small combined shortlist."""
    groups = [
        _distinct_document_sections(results, candidate_limit_per_query)
        for results in ranked_results
        if results
    ]
    from onyx.agents.v2.llm import BudgetedLLM

    protected = isinstance(llm, BudgetedLLM) and llm.protected_tokens > 0
    # Nomination cannot spend the capacity reserved for the final comparison.
    final_prompt_limit = 100000
    nomination_llm = (
        llm.with_token_reserve(llm.protected_tokens + final_prompt_limit + 1024)
        if protected
        else llm
    )
    nomination_diagnostics: list[dict[str, Any]] = [{} for _ in groups]
    calls = [
        (
            partial(
                selector,
                sections=group,
                user_query=user_query,
                llm=nomination_llm,
                max_sections=winners_per_query,
                max_chunks_per_section=1,
                try_to_fill_to_max=True,
                max_content_chars=500,
                center_first_evidence=True,
                use_query_highlights=True,
                compact_cards=True,
                **(
                    {"preparation_diagnostics": nomination_diagnostics[index]}
                    if protected
                    else {}
                ),
            ),
            (),
        )
        for index, group in enumerate(groups)
    ]
    first_pass = run_functions_tuples_in_parallel(calls)

    nominees: list[InferenceSection] = []
    seen: set[str] = set()
    for selected, _best_ids in first_pass:
        for section in selected:
            document_id = section.center_chunk.document_id
            if document_id in seen:
                continue
            seen.add(document_id)
            nominees.append(section)

    diagnostics: dict[str, Any] = {
        "query_group_count": len(groups),
        "candidate_counts": [len(group) for group in groups],
        "nominee_count": len(nominees),
        "nominee_document_ids": [s.center_chunk.document_id for s in nominees],
    }
    if protected:
        diagnostics["nomination_budget"] = nomination_diagnostics
    if not nominees:
        return [], None, diagnostics

    expanded = run_functions_tuples_in_parallel(
        [
            (
                partial(
                    expander,
                    section=section,
                    user_query=user_query,
                    llm=llm,
                    document_index=document_index,
                    expand_override=False,
                    context_expansion_strategy="adjacent_2",
                ),
                (),
            )
            for section in nominees
        ]
    )
    nominees = [section for section in expanded if section is not None]
    diagnostics["expanded_nominee_count"] = len(nominees)

    final_diagnostics: dict[str, Any] = {}
    selected, best_ids = selector(
        sections=nominees,
        user_query=user_query,
        llm=llm,
        max_sections=final_limit,
        max_chunks_per_section=5,
        try_to_fill_to_max=True,
        max_content_chars=5000,
        center_first_evidence=True,
        use_query_highlights=False,
        mark_full_documents=True,
        compact_cards=True,
        **(
            {
                "input_token_budget": max(
                    1, min(final_prompt_limit, llm.available_tokens() - 1024)
                ),
                "fit_only_if_needed": True,
                "preparation_diagnostics": final_diagnostics,
            }
            if protected
            else {}
        ),
    )
    if protected:
        diagnostics["final_selection_budget"] = final_diagnostics
        diagnostics["selection_degraded"] = any(
            d.get("fallback") for d in [*nomination_diagnostics, final_diagnostics]
        ) or bool(final_diagnostics.get("omitted_section_ids"))
    diagnostics["selected_count"] = len(selected)
    return selected, best_ids, diagnostics
