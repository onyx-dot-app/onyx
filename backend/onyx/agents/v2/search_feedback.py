"""Observable search feedback; no relevance classifier or completion decision."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from onyx.context.search.models import SearchDocsResponse


class EvidenceHistory:
    """Request-local exact paragraph history, independent of citation numbering."""

    def __init__(self) -> None:
        self.documents: set[str] = set()
        self.paragraphs: set[tuple[str, str]] = set()
        self.searches = 0

    def observe(self, content: str, citations: dict[int, str]) -> dict[str, Any]:
        documents = set(citations.values())
        paragraphs: set[tuple[str, str]] = set()
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            payload = None
        available = isinstance(payload, dict) and isinstance(
            payload.get("results"), list
        )
        if available:
            for passage in payload["results"]:
                if not isinstance(passage, dict):
                    available = False
                    break
                document = citations.get(passage.get("document"))
                text = passage.get("content")
                if document is None or not isinstance(text, str):
                    available = False
                    break
                for paragraph in re.split(r"\n\s*\n", text):
                    normalized = " ".join(paragraph.split())
                    if normalized:
                        paragraphs.add(
                            (document, hashlib.sha256(normalized.encode()).hexdigest())
                        )
        result = {
            "prior_search_count": self.searches,
            "new_document_count": len(documents - self.documents),
            "previously_seen_document_count": len(documents & self.documents),
            "new_document_citations": [
                n for n, d in citations.items() if d not in self.documents
            ],
            "paragraph_comparison_available": available,
            "new_exact_paragraph_count": len(paragraphs - self.paragraphs)
            if available
            else None,
            "repeated_exact_paragraph_count": len(paragraphs & self.paragraphs)
            if available
            else None,
            "interpretation": "Exact text novelty within this task, not relevance or new facts. The same document can contain new evidence.",
        }
        self.documents.update(documents)
        if available:
            self.paragraphs.update(paragraphs)
        self.searches += 1
        return result


def source_scope(content: str, rich: SearchDocsResponse) -> str:
    """Expose source metadata beside existing evidence without inferring scope."""
    try:
        payload = json.loads(content)
    except ValueError:
        return content
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return content
    docs = {d.document_id: d for d in rich.search_docs}
    for passage in payload["results"]:
        if not isinstance(passage, dict):
            continue
        doc = docs.get(rich.citation_mapping.get(passage.get("document")))
        metadata = passage.get("metadata", doc.metadata if doc else {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                pass
        passage["source_scope"] = {
            "title": passage.get("title"),
            "source_type": passage.get("source_type"),
            "indexed_updated_at": passage.get("updated_at"),
            "metadata": metadata,
        }
    payload["source_scope_note"] = (
        "Source metadata is descriptive, not proof that a passage applies to this request. "
        "Compare the environment, version, entity and time scope stated in the passage. "
        "Unspecified scope remains unknown. indexed_updated_at is the indexed source timestamp, "
        "not necessarily the publication or effective date. Different scopes need not conflict."
    )
    return json.dumps(payload, ensure_ascii=False)


def retrieval_outcome(rich: SearchDocsResponse) -> dict[str, Any]:
    # The pinned research backend has optional diagnostics; other snapshots may not.
    diagnostics = rich.model_dump(mode="json").get("search_tool_diagnostics") or {}
    expansion = diagnostics.get("context_expansion", {})
    failures = expansion.get("fallback_count")
    candidates = {d.document_id for d in rich.search_docs}
    evidence = set(rich.citation_mapping.values())
    state = (
        "evidence_returned"
        if evidence
        else "candidates_without_selected_evidence"
        if candidates
        else "no_candidates_returned"
    )
    return {
        "state": state,
        "candidate_document_count": len(candidates),
        "evidence_document_count": len(evidence),
        "candidate_documents_not_in_evidence": len(candidates - evidence),
        "context_expansion_fallback_count": failures,
        "partial_failure": bool(failures) if failures is not None else None,
        "expansion_not_relevant_retained_citations": [
            number
            for number, document in rich.citation_mapping.items()
            if document in expansion.get("not_relevant_retained_document_ids", [])
        ],
        "failure_observability": "context_expansion_only"
        if failures is not None
        else "unavailable",
        "interpretation": (
            "Counts cover this search's returned candidate window, not the corpus. "
            "Candidates excluded from evidence are not proven irrelevant. Expansion fallback "
            "preserves the original passage but may omit useful surrounding context. "
            "Retained citations marked not relevant by the expansion classifier are a separate "
            "relevance signal, not a tool failure or proof of irrelevance; assess their passages. "
            "No candidates does not establish that the requested information does not exist."
        ),
    }
