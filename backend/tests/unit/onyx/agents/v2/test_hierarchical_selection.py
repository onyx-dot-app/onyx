from types import SimpleNamespace
from typing import cast

from onyx.context.search.models import InferenceChunk, InferenceSection
from onyx.llm.interfaces import LLM
from onyx.tools.tool_implementations.search import hierarchical_selection as module


def _section(document_id: str) -> InferenceSection:
    return cast(
        InferenceSection,
        SimpleNamespace(center_chunk=SimpleNamespace(document_id=document_id)),
    )


def test_each_query_nominates_before_final_selection(monkeypatch):
    groups = {
        "q1": [_section("shared"), _section("only-q1")],
        "q2": [_section("shared"), _section("only-q2")],
    }
    monkeypatch.setattr(
        module,
        "_distinct_document_sections",
        lambda chunks, _limit: groups[cast(str, chunks[0])],
    )
    calls = []

    def selector(**kwargs):
        calls.append(kwargs)
        sections = kwargs["sections"]
        if kwargs.get("mark_full_documents"):
            return sections, [sections[0].center_chunk.document_id]
        return sections, None

    selected, best_ids, diagnostics = module.select_hierarchically(
        ranked_results=[
            cast(list[InferenceChunk], ["q1"]),
            cast(list[InferenceChunk], ["q2"]),
        ],
        user_query="original question",
        llm=cast(LLM, object()),
        document_index=object(),
        selector=selector,
        expander=lambda **kwargs: kwargs["section"],
    )

    assert diagnostics["nominee_document_ids"] == ["shared", "only-q1", "only-q2"]
    assert [s.center_chunk.document_id for s in selected] == [
        "shared",
        "only-q1",
        "only-q2",
    ]
    assert best_ids == ["shared"]
    assert len(calls) == 3
    assert calls[-1]["mark_full_documents"] is True
    assert calls[-1]["max_sections"] == 10
    assert calls[-1]["max_content_chars"] == 5000
