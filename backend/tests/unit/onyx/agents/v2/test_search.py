import json
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any, cast

import pytest

from onyx.agents.v2 import search as module
from onyx.agents.v2.models import ExecutionContext, SearchFeedback
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import (
    BaseFilters,
    PersonaSearchInfo,
    SearchDocsResponse,
)
from onyx.db.models import User
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.llm.interfaces import LLM
from onyx.llm.model_response import Choice, Message, ModelResponse
from onyx.server.query_and_chat.streaming_models import Packet, SearchToolQueriesDelta
from onyx.tools.models import ToolResponse


@pytest.mark.parametrize("task_anchor", [False, True])
@pytest.mark.parametrize("hierarchical_selection", [False, True])
@pytest.mark.parametrize("feedback", ["off", "navigation"])
@pytest.mark.parametrize("synthesize_answer", [False, True])
def test_each_followup_uses_its_own_objective_and_fresh_search(
    monkeypatch: pytest.MonkeyPatch,
    synthesize_answer: bool,
    feedback: SearchFeedback,
    task_anchor: bool,
    hierarchical_selection: bool,
) -> None:
    searches: list[dict[str, Any]] = []
    prompts: list[dict[str, Any]] = []
    ticks = iter(
        [0.0, 2.0, 2.0, 3.0, 4.0, 6.0, 6.0, 7.0]
        if synthesize_answer
        else [0.0, 2.0, 4.0, 6.0]
    )
    monkeypatch.setattr(module, "monotonic", lambda: next(ticks))

    class FakeSearch:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def run(self, **kwargs: Any) -> ToolResponse:
            override = kwargs["override_kwargs"]
            searches.append({"constructor": self.kwargs, "override": override})
            self.kwargs["emitter"].emit(
                Packet(
                    placement=kwargs["placement"],
                    obj=SearchToolQueriesDelta(
                        queries=["expanded " + override.original_query]
                    ),
                )
            )
            return ToolResponse(
                llm_facing_response="source evidence",
                rich_response=SearchDocsResponse(
                    search_docs=[],
                    displayed_docs=[],
                    citation_mapping={override.starting_citation_num: "doc1"},
                ),
            )

    def invoke(**kwargs: Any) -> ModelResponse:
        prompts.append(kwargs)
        return ModelResponse(
            id="test",
            created="0",
            choice=Choice(finish_reason="stop", message=Message(content="answer")),
        )

    monkeypatch.setattr(module, "SearchTool", FakeSearch)
    monkeypatch.setattr(
        module, "llm_generation_span", lambda *_a, **_kw: nullcontext(None)
    )
    monkeypatch.setattr(module, "record_llm_response", lambda *_a, **_kw: None)
    tool = module.InternalSearchAnswer(
        tool_id=1,
        user=cast(User, SimpleNamespace(id="user")),
        persona=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
        filters=None,
        index=cast(DocumentIndex, object()),
        llm=cast(LLM, SimpleNamespace(invoke=invoke)),
        synthesize_answer=synthesize_answer,
        feedback=feedback,
        task_anchor=task_anchor,
        hierarchical_selection=hierarchical_selection,
        final_selection_limit=8,
    )
    context = ExecutionContext(
        run_id="r1",
        task="Explain incident impact",
        remaining_seconds=20,
        remaining_tokens=10000,
        cancelled=lambda: False,
    )
    first = tool.run({"objective": "Find affected service"}, context)
    second = tool.run({"objective": "Find that service's customers"}, context)
    assert [s["override"].original_query for s in searches] == (
        [context.task, context.task]
        if task_anchor
        else ["Find affected service", "Find that service's customers"]
    )
    assert all(s["override"].skip_query_expansion is False for s in searches)
    assert all(
        s["override"].num_hits == (100 if hierarchical_selection else 50)
        for s in searches
    )
    assert all(
        s["constructor"]["hierarchical_selection"] is hierarchical_selection
        for s in searches
    )
    assert all(s["constructor"]["final_selection_limit"] == 8 for s in searches)
    assert all("expand_current_objective" not in s["constructor"] for s in searches)
    assert all("lexical_keyword_queries" not in s["constructor"] for s in searches)
    assert all(s["constructor"]["bypass_acl"] is False for s in searches)
    assert all(s["override"].adaptive_search is None for s in searches)
    assert all(s["override"].answer_verification is None for s in searches)
    assert (
        searches[0]["constructor"]["emitter"]
        is not searches[1]["constructor"]["emitter"]
    )
    assert first.citation_mapping == {1: "doc1"}
    assert second.citation_mapping == {2: "doc1"}
    assert first.receipt["executed_queries"] == [
        "expanded " + (context.task if task_anchor else "Find affected service")
    ]
    assert second.receipt["executed_queries"] == [
        "expanded " + (context.task if task_anchor else "Find that service's customers")
    ]
    assert first.receipt["retrieval_ms"] == second.receipt["retrieval_ms"] == 2000
    if not synthesize_answer:
        assert not prompts
        assert first.answer is second.answer is None
        assert first.status == second.status == "success"
        assert first.content == second.content == "source evidence"
        assert first.receipt["answer_synthesis_enabled"] is False
        assert (
            first.receipt["answer_synthesis_ms"]
            == second.receipt["answer_synthesis_ms"]
            == 0
        )
        return
    assert json.loads(prompts[1]["prompt"][1].content)["overall_task"] == context.task
    assert (
        json.loads(prompts[1]["prompt"][1].content)["retrieval_objective"]
        == "Find that service's customers"
    )
    assert all(p["tools"] == [] for p in prompts)
    assert all(p["max_tokens"] is None for p in prompts)
    assert first.answer == second.answer == "answer"
    assert first.receipt["retrieval_ms"] == second.receipt["retrieval_ms"] == 2000
    assert (
        first.receipt["answer_synthesis_ms"]
        == second.receipt["answer_synthesis_ms"]
        == 1000
    )


def test_search_objective_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        module.SearchObjective.model_validate(
            {"objective": "find docs", "bypass_acl": True}
        )


def test_internal_search_answer_passes_filter_detection_and_explicit_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeSearch:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        def run(self, **_kwargs: Any) -> ToolResponse:
            return ToolResponse(
                llm_facing_response="source evidence",
                rich_response=SearchDocsResponse(
                    search_docs=[],
                    displayed_docs=[],
                    citation_mapping={1: "doc1"},
                ),
            )

    monkeypatch.setattr(module, "SearchTool", FakeSearch)
    filters = BaseFilters(
        source_type=[DocumentSource.WEB],
        document_set=["selected"],
    )
    tool = module.InternalSearchAnswer(
        tool_id=1,
        user=cast(User, SimpleNamespace(id="user")),
        persona=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
        filters=filters,
        index=cast(DocumentIndex, object()),
        llm=cast(LLM, object()),
        auto_detect_filters=False,
    )
    result = tool.run(
        {"objective": "Find selected docs"},
        ExecutionContext(
            run_id="r1",
            task="Explain incident impact",
            remaining_seconds=20,
            remaining_tokens=10000,
            cancelled=lambda: True,
        ),
    )
    assert captured["auto_detect_filters"] is False
    assert captured["user_selected_filters"] is filters
    assert captured["bypass_acl"] is False
    assert result.receipt["requested_filters"] == filters.model_dump(mode="json")
