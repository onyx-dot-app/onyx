from __future__ import annotations

import json

import pytest

from onyx.agents.v2.context import ContextBudgetExceeded, ContextState
from onyx.agents.v2.models import HarnessPolicy, ToolOutput


def _count_chars(text: str) -> int:
    return len(text)


def _state(max_store_bytes: int = 4096) -> ContextState:
    return ContextState(
        HarnessPolicy(max_store_bytes=max_store_bytes),
        token_counter=_count_chars,
    )


def test_add_preserves_receipt_and_result_ref_when_preview_is_omitted() -> None:
    state = _state()
    ref = state.add(
        "internal_search",
        "find upload limits",
        ToolOutput(
            content="evidence " * 200,
            answer="file uploads default to 32 MB",
            receipt={"query": "multipart upload limits"},
            document_ids=["doc-1"],
        ),
    )

    rendered = json.loads(state.render(max_tokens=900))

    assert rendered["receipts"][0]["result_ref"] == ref
    assert rendered["receipts"][0]["tool_receipt"] == {
        "query": "multipart upload limits"
    }
    assert rendered["results"][0]["result_ref"] == ref


def test_protected_receipt_overflow_raises() -> None:
    state = _state()
    state.add(
        "internal_search",
        "x" * 1000,
        ToolOutput(content="short", receipt={"query": "q"}),
    )

    with pytest.raises(ContextBudgetExceeded):
        state.render(max_tokens=10)


def test_read_refetches_bounded_content_with_offsets() -> None:
    state = _state()
    ref = state.add(
        "internal_search",
        "objective",
        ToolOutput(content="abcdef", answer="full answer should not be returned"),
    )

    first = state.read(ref, max_chars=2)
    second = state.read(ref, offset=first["next_offset"], max_chars=4)

    assert first["content"] == "ab"
    assert "answer" not in first
    assert first["has_more"] is True
    assert second["content"] == "cdef"
    assert second["has_more"] is False


def test_unknown_refs_are_rejected() -> None:
    state = _state()

    with pytest.raises(KeyError):
        state.read("result_9999")

    with pytest.raises(KeyError):
        state.output("result_9999")


def test_output_returns_deep_copy() -> None:
    state = _state()
    ref = state.add(
        "internal_search",
        "objective",
        ToolOutput(content="content", receipt={"query": "original"}),
    )

    output = state.output(ref)
    output.receipt["query"] = "mutated"

    assert state.output(ref).receipt == {"query": "original"}


def test_exact_duplicate_markers_use_body_not_document_id() -> None:
    state = _state()
    first = state.add(
        "internal_search",
        "first",
        ToolOutput(content="same passage", document_ids=["doc-1"]),
    )
    second = state.add(
        "internal_search",
        "second",
        ToolOutput(content="same passage", document_ids=["doc-2"]),
    )
    third = state.add(
        "internal_search",
        "third",
        ToolOutput(content="new passage", document_ids=["doc-1"]),
    )

    receipts = state.receipts

    assert receipts[0]["exact_duplicate"] is False
    assert receipts[1]["result_ref"] == second
    assert receipts[1]["exact_duplicate"] is True
    assert receipts[1]["duplicate_of"] == first
    assert receipts[2]["result_ref"] == third
    assert receipts[2]["exact_duplicate"] is False


def test_large_outputs_are_store_bounded_and_marked_truncated() -> None:
    state = _state(max_store_bytes=4096)
    ref = state.add(
        "internal_search",
        "large",
        ToolOutput(
            content="x" * 20_000,
            answer="answer",
            receipt={"query": "large"},
        ),
    )

    fetched = state.read(ref, max_chars=20_000)
    receipt = state.receipts[0]

    assert len(state.output(ref).model_dump_json().encode("utf-8")) <= 4096
    assert len(fetched["content"]) < 20_000
    assert receipt["truncated"] is True


def test_huge_untrusted_receipts_are_compacted() -> None:
    state = _state()
    ref = state.add(
        "internal_search",
        "objective",
        ToolOutput(
            content="content",
            receipt={"query": "q", "raw": "x" * 100_000},
        ),
    )

    receipt = state.receipts[0]

    assert receipt["result_ref"] == ref
    assert receipt["tool_receipt"]["truncated"] is True
    assert receipt["tool_receipt"]["truncated_note"]


def test_large_search_receipt_preserves_navigation_ledger() -> None:
    state = _state(max_store_bytes=20_000)
    navigation = {
        "diagnostics_available": True,
        "queries": [
            {
                "query_id": index,
                "query": "semantic query " + "x" * 500,
                "returned_documents": 100,
                "unique_to_this_query": 40,
                "evidence_citations": [index],
            }
            for index in range(1, 7)
        ],
        "stages": {"retrieved_documents": 400, "selection_input": 50, "selected": 5},
        "alternatives": [
            {
                "handle": f"candidate_1_{index}",
                "document_id": f"doc-{index}",
                "title": "candidate title " + "t" * 500,
                "query_id": index,
                "rank": index,
                "stage": "not_selected",
                "excerpt": "candidate evidence " + "e" * 2_000,
                "available_chars": 6_000,
            }
            for index in range(1, 4)
        ],
        "guidance": "g" * 5_000,
    }
    state.add(
        "internal_search",
        "objective",
        ToolOutput(
            content="evidence",
            receipt={
                "selection_question": "find the exact historical record",
                "executed_queries": ["q" * 2_000] * 6,
                "retrieved_document_count": 400,
                "evidence_document_count": 5,
                "navigation": navigation,
            },
        ),
    )

    compact = state.receipts[0]["tool_receipt"]

    assert compact["truncated"] is True
    assert len(json.dumps(compact, separators=(",", ":"))) <= 6_000
    assert compact["navigation"]["queries"][0]["query_id"] == 1
    assert compact["navigation"]["alternatives"][0]["handle"] == "candidate_1_1"
    assert "inspect" in compact["navigation"]["guidance"]


def test_tight_budget_gives_latest_answer_first_claim_on_preview_budget() -> None:
    state = _state(max_store_bytes=4096)
    old_ref = state.add(
        "internal_search",
        "first broad search",
        ToolOutput(
            content="old evidence " * 120,
            answer="old answer",
            receipt={"query": "old"},
        ),
    )
    latest_ref = state.add(
        "internal_search",
        "follow-up exact search",
        ToolOutput(
            content="latest evidence " * 120,
            answer="latest answer",
            receipt={"query": "latest"},
        ),
    )

    rendered = json.loads(state.render(max_tokens=1150))
    results_by_ref = {result["result_ref"]: result for result in rendered["results"]}

    assert [receipt["result_ref"] for receipt in rendered["receipts"]] == [
        old_ref,
        latest_ref,
    ]
    assert rendered["results"][0]["result_ref"] == latest_ref
    assert results_by_ref[latest_ref]["answer"] == "latest answer"
    assert results_by_ref[latest_ref].get("content_preview")
    assert old_ref in results_by_ref
    assert state.read(old_ref, max_chars=20)["content"] == "old evidence old evi"
