"""Search receipts: deterministic retrieval metadata appended to an internal search
tool response so the next model call can see what the search actually executed.

This is an experimental, receipt-only treatment. It adds no model call, no tool and
no prompt change. The original evidence string stays an untouched prefix. The receipt
schema, math, strings and key order below are the evaluated ones and must not drift
without a new evaluation.
"""

import json
from typing import TypedDict

from onyx.context.search.models import (
    RetrievalCandidateLane,
    SearchDocsResponse,
    SearchReceiptScope,
    SearchRetrievalDiagnostics,
)
from onyx.db.models import User
from onyx.feature_flags.factory import get_default_feature_flag_provider
from onyx.tools.models import ToolResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# PostHog flag. Receipts default to on: an undefined flag or no PostHog keeps
# them on, so the flag can only turn receipts off (or on for a subset once defined).
SEARCH_RECEIPTS_FLAG = "onyx-search-receipts"

RECEIPT_PREFIX = "\n\nSEARCH RECEIPT (retrieval metadata, not source evidence):\n"

_COVERAGE = "Ranked, capped retrieval; not an exhaustive corpus scan."
_INTERPRETATION = (
    "Overlap is not answer confidence. Repeated or empty results do not prove the "
    "information is absent. Use observed queries and missing facts to choose a "
    "complementary follow-up when needed."
)


def search_receipts_enabled(user: User | None) -> bool:
    """Evaluate the search receipts flag once per chat message."""
    return (
        get_default_feature_flag_provider().feature_enabled_for_user_tenant_or_default(
            SEARCH_RECEIPTS_FLAG,
            user,
            get_current_tenant_id(),
            default=True,
        )
    )


class ReceiptScope(TypedDict):
    user_filters: dict[str, object] | None
    persona_document_sets: list[str]
    acl_enforced: bool


class ReceiptQueryEntry(TypedDict):
    query: str
    hybrid_alpha: float | None
    returned_documents: int
    new_documents_this_task: int


class SearchReceipt(TypedDict):
    executed_queries: list[ReceiptQueryEntry]
    retrieved_documents: int
    new_candidate_documents: int
    repeated_candidate_documents: int
    after_merge_cap: int
    returned_evidence_documents: int
    scope: ReceiptScope
    coverage: str
    interpretation: str


def _lane_document_ids(lane: RetrievalCandidateLane) -> set[str]:
    """Distinct documents a lane returned. The single definition of "candidate"."""
    return {chunk.document_id for chunk in lane.returned_chunks}


def build_search_receipt(
    *,
    diagnostics: SearchRetrievalDiagnostics,
    citation_mapping: dict[int, str],
    seen_document_ids: set[str],
    scope: SearchReceiptScope,
) -> SearchReceipt:
    """Compute the receipt and then add this search's candidates to
    `seen_document_ids`. Counts are distinct documents, never chunks."""
    docs: set[str] = set()
    query_entries: list[ReceiptQueryEntry] = []
    # `seen` is only updated after every lane is counted, so a document returned by
    # two lanes of the same response is new in both lanes.
    for lane in diagnostics.retrieval_candidates:
        ids = _lane_document_ids(lane)
        docs.update(ids)
        query_entries.append(
            {
                "query": lane.query,
                "hybrid_alpha": lane.hybrid_alpha,
                "returned_documents": len(ids),
                "new_documents_this_task": len(ids - seen_document_ids),
            }
        )

    receipt: SearchReceipt = {
        "executed_queries": query_entries,
        "retrieved_documents": len(docs),
        "new_candidate_documents": len(docs - seen_document_ids),
        "repeated_candidate_documents": len(docs & seen_document_ids),
        "after_merge_cap": len(
            set(diagnostics.merged_candidate_document_ids_after_cap)
        ),
        "returned_evidence_documents": len(set(citation_mapping.values())),
        "scope": {
            "user_filters": scope.user_filters,
            "persona_document_sets": scope.persona_document_sets,
            "acl_enforced": scope.acl_enforced,
        },
        "coverage": _COVERAGE,
        "interpretation": _INTERPRETATION,
    }
    seen_document_ids.update(docs)
    return receipt


def append_search_receipt(
    original_response: str,
    *,
    diagnostics: SearchRetrievalDiagnostics,
    citation_mapping: dict[int, str],
    seen_document_ids: set[str],
    scope: SearchReceiptScope,
) -> str:
    receipt = build_search_receipt(
        diagnostics=diagnostics,
        citation_mapping=citation_mapping,
        seen_document_ids=seen_document_ids,
        scope=scope,
    )
    return original_response + RECEIPT_PREFIX + json.dumps(receipt, ensure_ascii=False)


def maybe_append_search_receipt(
    *,
    tool_response: ToolResponse,
    seen_document_ids: set[str],
) -> None:
    """Append a receipt to `tool_response.llm_facing_response` in place, exactly once
    per response. When the metadata needed for an honest receipt is missing the
    response is left untouched and the reason is logged."""
    rich_response = tool_response.rich_response
    tool_call_id = (
        tool_response.tool_call.tool_call_id if tool_response.tool_call else None
    )
    if not isinstance(rich_response, SearchDocsResponse):
        _log_unavailable("not_search_docs_response", tool_call_id)
        return
    diagnostics = rich_response.retrieval_diagnostics
    if diagnostics is None:
        _log_unavailable("missing_retrieval_diagnostics", tool_call_id)
        return
    if diagnostics.receipt_scope is None:
        # No receipt, but the search still ran: its candidates count as seen so a
        # later receipt in this turn does not report them as new.
        for lane in diagnostics.retrieval_candidates:
            seen_document_ids.update(_lane_document_ids(lane))
        _log_unavailable("unrepresentable_scope", tool_call_id)
        return

    tool_response.llm_facing_response = append_search_receipt(
        tool_response.llm_facing_response,
        diagnostics=diagnostics,
        citation_mapping=rich_response.citation_mapping,
        seen_document_ids=seen_document_ids,
        scope=diagnostics.receipt_scope,
    )


def _log_unavailable(reason: str, tool_call_id: str | None) -> None:
    logger.info(
        "search_receipt_unavailable reason=%s tool_call_id=%s", reason, tool_call_id
    )
