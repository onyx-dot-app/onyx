from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import math
import time
from typing import Any

import httpx
from cohere import AsyncClient as CohereAsyncClient
from cohere.types import RerankResponse

from onyx.context.search.models import InferenceSection
from onyx.natural_language_processing.search_nlp_models import EmbeddingModel
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import traced_llm_call
from shared_configs.enums import EmbeddingProvider

COHERE_RERANK_PROVIDER = "cohere"
COHERE_RERANK_MODEL = "rerank-v4.0-fast"
COHERE_RERANK_TIMEOUT_SECONDS = 30.0
COHERE_RERANK_MAX_CANDIDATES = 600
COHERE_RERANK_MAX_TEXT_CHARS = 8000
COHERE_RERANK_DEFAULT_TOP_N = 10
COHERE_RERANK_MIN_TOP_N = 1
COHERE_RERANK_MAX_TOP_N = 20
COHERE_RERANK_MAX_CHUNKS_PER_DOC = 1


def select_sections_with_cohere_rerank(
    *,
    query: str,
    sections: list[InferenceSection],
    embedding_model: EmbeddingModel,
    include_candidate_scores: bool = False,
    top_n: int = COHERE_RERANK_DEFAULT_TOP_N,
) -> tuple[list[InferenceSection], dict[str, Any]]:
    if not isinstance(top_n, int) or isinstance(top_n, bool):
        raise TypeError("cohere_rerank top_n must be an integer")
    if top_n < COHERE_RERANK_MIN_TOP_N or top_n > COHERE_RERANK_MAX_TOP_N:
        raise ValueError(
            f"cohere_rerank top_n must be between {COHERE_RERANK_MIN_TOP_N} "
            f"and {COHERE_RERANK_MAX_TOP_N}"
        )
    start = time.monotonic()
    candidate_sections = sections[:COHERE_RERANK_MAX_CANDIDATES]
    texts = [_section_to_rerank_text(section) for section in candidate_sections]
    truncated_count = sum(
        1 for text in texts if len(text) > COHERE_RERANK_MAX_TEXT_CHARS
    )
    texts = [text[:COHERE_RERANK_MAX_TEXT_CHARS] for text in texts]

    if not candidate_sections:
        diagnostics = _build_base_diagnostics(
            input_count=len(candidate_sections),
            text_lengths=[len(text) for text in texts],
            truncation_count=truncated_count,
            elapsed_ms=_elapsed_ms(start),
            requested_top_n=top_n,
        )
        diagnostics.update(
            {
                "status": "empty_candidates",
                "reason": "empty_candidates",
                "score_count": 0,
                "score_coverage": "empty_candidates",
                "all_indices_returned": True,
                "finite_scores": True,
                "selected_original_indices": [],
                "selected_scores": [],
                "selected_doc_ids": [],
                "selected_count": 0,
            }
        )
        if include_candidate_scores:
            diagnostics["candidate_scores"] = []
        return [], diagnostics

    if embedding_model.provider_type != EmbeddingProvider.COHERE:
        raise RuntimeError(
            "cohere_rerank selection requires the active embedding provider to be Cohere"
        )
    if not embedding_model.api_key:
        raise RuntimeError(
            "cohere_rerank selection requires an active Cohere embedding API key"
        )

    response = _run_cohere_rerank(
        query=query,
        documents=texts,
        api_key=embedding_model.api_key,
    )
    scores_by_index = _scores_by_index(response=response, expected_count=len(texts))
    ranked_indices = sorted(
        scores_by_index,
        key=lambda index: (-scores_by_index[index], index),
    )
    selected_indices = ranked_indices[:top_n]
    selected_sections = [candidate_sections[index] for index in selected_indices]

    diagnostics = _build_base_diagnostics(
        input_count=len(candidate_sections),
        text_lengths=[len(text) for text in texts],
        truncation_count=truncated_count,
        elapsed_ms=_elapsed_ms(start),
        requested_top_n=top_n,
    )
    diagnostics.update(
        {
            "status": "succeeded",
            "score_count": len(scores_by_index),
            "score_coverage": "complete",
            "all_indices_returned": True,
            "finite_scores": True,
            "billed_search_units": _billed_search_units_from_response(response),
            "selected_original_indices": selected_indices,
            "selected_scores": [scores_by_index[index] for index in selected_indices],
            "selected_doc_ids": [
                section.center_chunk.document_id for section in selected_sections
            ],
            "selected_count": len(selected_sections),
        }
    )
    if include_candidate_scores:
        diagnostics["candidate_scores"] = _build_candidate_score_diagnostics(
            sections=candidate_sections,
            texts=texts,
            scores_by_index=scores_by_index,
        )
    return selected_sections, diagnostics


def _build_base_diagnostics(
    *,
    input_count: int,
    text_lengths: list[int],
    truncation_count: int,
    elapsed_ms: float,
    requested_top_n: int,
) -> dict[str, Any]:
    return {
        "provider": COHERE_RERANK_PROVIDER,
        "model": COHERE_RERANK_MODEL,
        "client": "cohere-python",
        "client_version": _cohere_version(),
        "timeout_seconds": COHERE_RERANK_TIMEOUT_SECONDS,
        "max_retries": 0,
        "max_candidates": COHERE_RERANK_MAX_CANDIDATES,
        "max_text_chars": COHERE_RERANK_MAX_TEXT_CHARS,
        "max_chunks_per_doc": COHERE_RERANK_MAX_CHUNKS_PER_DOC,
        "requested_top_n": requested_top_n,
        "text_policy": "title + center-first content",
        "input_count": input_count,
        "text_lengths": text_lengths,
        "truncation_count": truncation_count,
        "elapsed_ms": elapsed_ms,
        "cost_usd": None,
        "cost_unknown": True,
    }


def _section_to_rerank_text(section: InferenceSection) -> str:
    center_chunk = section.center_chunk
    title = center_chunk.semantic_identifier or center_chunk.title or ""
    content_parts = [center_chunk.content]
    seen_chunk_ids = {center_chunk.unique_id}
    for chunk in section.chunks:
        if chunk.unique_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk.unique_id)
        content_parts.append(chunk.content)
    return f"Title: {title}\nContent:\n" + "\n\n".join(content_parts)


def _run_cohere_rerank(
    query: str, documents: list[str], api_key: str
) -> RerankResponse:
    async def rerank() -> RerankResponse:
        httpx_client = httpx.AsyncClient(timeout=COHERE_RERANK_TIMEOUT_SECONDS)
        client = CohereAsyncClient(
            api_key=api_key,
            timeout=COHERE_RERANK_TIMEOUT_SECONDS,
            max_retries=0,
            httpx_client=httpx_client,
        )
        async with httpx_client:
            with traced_llm_call(
                flow=LLMFlow.RERANK,
                model=COHERE_RERANK_MODEL,
                provider=COHERE_RERANK_PROVIDER,
                extra_config={"num_passages": str(len(documents))},
                input_messages=[{"query": query, "document_count": len(documents)}],
            ):
                return await asyncio.wait_for(
                    client.rerank(
                        query=query,
                        documents=documents,
                        model=COHERE_RERANK_MODEL,
                        max_chunks_per_doc=COHERE_RERANK_MAX_CHUNKS_PER_DOC,
                    ),
                    timeout=COHERE_RERANK_TIMEOUT_SECONDS,
                )

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(rerank())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _scores_by_index(response: RerankResponse, expected_count: int) -> dict[int, float]:
    results = response.results
    scores_by_index: dict[int, float] = {}
    for result in results:
        index = result.index
        score = float(result.relevance_score)
        if not isinstance(index, int) or index < 0 or index >= expected_count:
            raise RuntimeError("Cohere rerank returned an out-of-range result index")
        if index in scores_by_index:
            raise RuntimeError("Cohere rerank returned a duplicate result index")
        if not math.isfinite(score):
            raise RuntimeError("Cohere rerank returned a non-finite relevance score")
        scores_by_index[index] = score
    if len(scores_by_index) != expected_count:
        raise RuntimeError("Cohere rerank did not return scores for every candidate")
    return scores_by_index


def _billed_search_units_from_response(response: RerankResponse) -> float | None:
    meta = response.meta
    if meta is None or meta.billed_units is None:
        return None
    return meta.billed_units.search_units


def _build_candidate_score_diagnostics(
    *,
    sections: list[InferenceSection],
    texts: list[str],
    scores_by_index: dict[int, float],
) -> list[dict[str, Any]]:
    return [
        {
            "index": index,
            "document_id": section.center_chunk.document_id,
            "center_chunk_id": section.center_chunk.unique_id,
            "score": scores_by_index[index],
            "text_sha256": hashlib.sha256(texts[index].encode("utf-8")).hexdigest(),
        }
        for index, section in enumerate(sections)
    ]


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 3)


def _cohere_version() -> str | None:
    try:
        return importlib.metadata.version("cohere")
    except importlib.metadata.PackageNotFoundError:
        return None
