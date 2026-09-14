import __future__

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast

import pytest

from onyx.agents.v2.context import ContextBudgetExceeded, ContextState
from onyx.agents.v2.models import HarnessPolicy, ToolOutput
from onyx.agents.v2.search_feedback import (
    EvidenceHistory,
    retrieval_outcome,
    source_scope,
)
from onyx.context.search.models import SearchDocsResponse
from onyx.tools.tool_implementations.search import search_tool


def evidence(number, text):
    return json.dumps({"results": [{"document": number, "content": text}]})


def test_novelty_ignores_citation_number_and_whitespace_but_keeps_new_passages():
    history = EvidenceHistory()
    first = history.observe(evidence(1, "first fact\n\nsecond fact"), {1: "a"})
    second = history.observe(evidence(8, "first   fact\n\nthird fact"), {8: "a"})
    assert first["new_document_count"] == 1
    assert second["new_document_count"] == 0
    assert second["new_exact_paragraph_count"] == 1
    assert second["repeated_exact_paragraph_count"] == 1
    assert second["prior_search_count"] == 1
    assert history.observe("unparseable", {9: "b"})["new_exact_paragraph_count"] is None
    assert (
        EvidenceHistory().observe(evidence(1, "first fact"), {1: "a"})[
            "new_document_count"
        ]
        == 1
    )


def test_source_metadata_does_not_change_evidence_or_invent_scope():
    rich = SearchDocsResponse(search_docs=[], citation_mapping={1: "a"})
    content = json.dumps(
        {
            "results": [
                {
                    "document": 1,
                    "title": "Title",
                    "updated_at": "2026-09-08",
                    "metadata": '{"id":"a"}',
                    "content": "Exact evidence",
                }
            ]
        }
    )
    result = json.loads(source_scope(content, rich))
    passage = result["results"][0]
    assert passage["content"] == "Exact evidence"
    assert passage["source_scope"]["metadata"] == {"id": "a"}
    assert "environment" not in passage["source_scope"]
    assert "not necessarily the publication" in result["source_scope_note"]


@pytest.mark.parametrize(
    "candidates,citations,fallbacks,state",
    [
        ([], {}, 0, "no_candidates_returned"),
        (["a"], {}, 0, "candidates_without_selected_evidence"),
        (["a", "b"], {1: "a"}, 2, "evidence_returned"),
    ],
)
def test_outcomes_preserve_retrieval_and_failure_distinctions(
    candidates, citations, fallbacks, state
):
    rich = SearchDocsResponse.model_construct(
        search_docs=[SimpleNamespace(document_id=d) for d in candidates],
        citation_mapping=citations,
        search_tool_diagnostics={"context_expansion": {"fallback_count": fallbacks}},
    )
    result = retrieval_outcome(rich)
    assert result["state"] == state
    assert result["partial_failure"] == bool(fallbacks)
    assert result["candidate_documents_not_in_evidence"] == len(
        set(candidates) - set(citations.values())
    )


def test_missing_failure_diagnostics_are_unknown():
    result = retrieval_outcome(SearchDocsResponse(search_docs=[], citation_mapping={}))
    assert result["partial_failure"] is None


@pytest.mark.parametrize(
    "behavior,expected_count", [("success", 0), ("none", 0), ("error", 1)]
)
def test_real_expansion_fallback_preserves_evidence_and_reports_degradation(
    behavior, expected_count
):
    # Execute the actual nested backend function without running retrieval/LLMs.
    tree = ast.parse(Path(search_tool.__file__).read_text())
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "expand_section_safe"
    )
    fallbacks = []
    not_relevant = []
    original = SimpleNamespace(center_chunk=SimpleNamespace(document_id="a"))

    def expand(**_kwargs):
        if behavior == "error":
            raise RuntimeError("simulated expansion failure")
        return "expanded" if behavior == "success" else None

    namespace = {
        "expand_section_with_context": expand,
        "expansion_fallbacks": fallbacks,
        "expansion_not_relevant": not_relevant,
        "logger": SimpleNamespace(warning=lambda *_args: None),
    }
    exec(  # noqa: S102 -- executes the trusted local backend function under test
        compile(
            ast.Module(body=[function], type_ignores=[]),
            "<backend-expansion>",
            "exec",
            flags=__future__.annotations.compiler_flag,
        ),
        namespace,
    )
    expand_section_safe = cast(Callable[..., object], namespace["expand_section_safe"])
    result = expand_section_safe(original, "query", None, None, False, "llm")
    assert result == ("expanded" if behavior == "success" else original)
    assert len(fallbacks) == expected_count
    assert not_relevant == (["a"] if behavior == "none" else [])


def test_visibility_protects_markers_for_all_results_and_reads_exact_remainder():
    state = ContextState(HarnessPolicy(search_feedback="visibility"), len)
    first = state.add("internal_search", "first", ToolOutput(content="a" * 2000))
    state.add("internal_search", "second", ToolOutput(content="b" * 2000))
    rendered = state.render(1800)
    assert len(rendered) <= 1800
    for entry in json.loads(rendered)["results"]:
        assert entry["content_truncated"]
        assert entry["read_more"]["offset"] == len(entry.get("content_preview", ""))
        assert entry["visibility"]["omitted_stored_chars"] > 0
        read = state.read(entry["result_ref"], entry["read_more"]["offset"])
        assert (
            entry.get("content_preview", "") + read["content"]
            == state.output(entry["result_ref"]).content
        )
    assert state.read(first)["source_completeness"] == "unknown"
    with pytest.raises(ContextBudgetExceeded):
        state.render(100)


def test_visibility_distinguishes_store_loss_from_preview_omission():
    state = ContextState(
        HarnessPolicy(search_feedback="visibility", max_store_bytes=4096), len
    )
    ref = state.add("internal_search", "query", ToolOutput(content="x" * 10000))
    entry = json.loads(state.render(10000))["results"][0]
    assert entry["visibility"]["store_truncated"]
    assert not entry["content_truncated"]
    assert entry["read_more"] is None
    assert state.read(ref)["store_truncated"]
