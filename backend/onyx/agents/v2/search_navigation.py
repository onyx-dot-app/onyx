"""Bounded, observed search provenance and request-local candidate inspection."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from onyx.agents.v2.models import ToolOutput


class SearchNavigation:
    def __init__(self) -> None:
        self.searches = 0
        self.seen_candidates: set[str] = set()
        self.candidates: dict[str, dict[str, Any]] = {}

    def observe(
        self, diagnostics: dict[str, Any], citations: dict[int, str]
    ) -> dict[str, Any]:
        self.searches += 1
        retrieval = diagnostics.get("retrieval", {})
        queries = retrieval.get("retrieval_candidates", [])
        query_docs = [{c["document_id"] for c in q["returned_chunks"]} for q in queries]
        frequencies = Counter(d for docs in query_docs for d in docs)
        all_docs = set(frequencies)
        evidence = set(citations.values())
        merged = set(retrieval.get("merged_candidate_document_ids_after_cap", []))
        stages = retrieval.get("selection_stage_document_ids", {})
        summaries = []
        for index, (query, docs) in enumerate(zip(queries, query_docs, strict=True), 1):
            summaries.append(
                {
                    "query_id": index,
                    "query": query["query"],
                    "hybrid_alpha": query.get("hybrid_alpha"),
                    "returned_documents": len(docs),
                    "unique_to_this_query": sum(frequencies[d] == 1 for d in docs),
                    "new_documents_this_task": len(docs - self.seen_candidates),
                    "evidence_citations": [
                        n for n, d in citations.items() if d in docs
                    ],
                }
            )
        alternatives = []
        chosen = set(evidence)
        # Round-robin across ranks and queries, not just the first query's hits.
        for rank in range(8):
            for index, query in enumerate(queries, 1):
                chunks = query["returned_chunks"]
                if rank >= len(chunks):
                    continue
                chunk = chunks[rank]
                doc = chunk["document_id"]
                if doc in chosen or not chunk.get("content") or len(alternatives) >= 3:
                    continue
                chosen.add(doc)
                handle = f"candidate_{self.searches}_{len(alternatives) + 1}"
                self.candidates[handle] = dict(chunk)
                stage = (
                    "outside_merged_cap"
                    if doc not in merged
                    else "outside_selection_input"
                    if doc not in stages.get("selection_input", [])
                    else "not_selected"
                    if doc not in stages.get("selected", [])
                    else "not_in_final_evidence"
                )
                alternatives.append(
                    {
                        "handle": handle,
                        "document_id": doc,
                        "chunk_id": chunk["chunk_id"],
                        "title": chunk.get("title"),
                        "query_id": index,
                        "rank": chunk["rank"],
                        "stage": stage,
                        "excerpt": chunk["content"][:650],
                        "available_chars": len(chunk["content"]),
                        "source_chunk_chars": chunk.get("content_total_chars"),
                    }
                )
        # At most 36 cached passages (12 normal tool calls), with defensive eviction.
        while len(self.candidates) > 36:
            del self.candidates[next(iter(self.candidates))]
        output = {
            "diagnostics_available": bool(queries),
            "queries": summaries,
            "stages": {
                "retrieved_documents": len(all_docs),
                "after_merge_cap": len(merged),
                **{name: len(set(ids)) for name, ids in stages.items()},
            },
            "repeated_candidate_documents": len(all_docs & self.seen_candidates),
            "new_candidate_documents": len(all_docs - self.seen_candidates),
            "alternatives": alternatives,
            "guidance": (
                "Alternatives are retrieved leads, not verified answers or citations. Inspect a promising handle "
                "using internal_search(objective=missing fact, candidate_handle=handle, offset=0); this reads "
                "cached authorized text without another retrieval or LLM call. Compare exact entity, version, "
                "event date and requested quantity in excerpts; unstated constraints remain unknown. "
                "Indexed timestamps are not event dates. Query ranks and overlap are not answer confidence. "
                "If a clue is missing, use it in a materially different search objective; do not assume a "
                "nearby topic is the requested entity. Repeated candidates do not prove corpus absence."
            ),
        }
        self.seen_candidates.update(all_docs)
        return output

    def inspect(self, handle: str, offset: int, citation: int) -> ToolOutput:
        chunk = self.candidates.get(handle)
        if chunk is None:
            return ToolOutput(
                status="error",
                content="Unknown or expired candidate handle; use a handle from this task's search receipt.",
                receipt={"operation": "inspect_candidate"},
            )
        content = chunk["content"]
        if offset >= len(content):
            return ToolOutput(
                status="error",
                content="Offset is outside the cached passage.",
                receipt={
                    "operation": "inspect_candidate",
                    "available_chars": len(content),
                },
            )
        end = min(offset + 3000, len(content))
        doc = chunk["document_id"]
        return ToolOutput(
            content=json.dumps(
                {
                    "results": [
                        {
                            "document": citation,
                            "document_id": doc,
                            "chunk_id": chunk["chunk_id"],
                            "title": chunk.get("title"),
                            "source_type": chunk.get("source_type"),
                            "indexed_updated_at": chunk.get("indexed_updated_at"),
                            "content": content[offset:end],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            document_ids=[doc],
            citation_mapping={citation: doc},
            receipt={
                "operation": "inspect_candidate",
                "candidate_handle": handle,
                "offset": offset,
                "next_offset": end if end < len(content) else None,
                "available_chars": len(content),
                "source_chunk_chars": chunk.get("content_total_chars"),
                "cached_passage_truncated": len(content)
                < chunk.get("content_total_chars", len(content)),
                "coverage": "Cached retrieved chunk only; no new index search or adjacent-section fetch.",
            },
        )
