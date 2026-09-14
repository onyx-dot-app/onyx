from types import SimpleNamespace
from typing import cast

import pytest

from onyx.agents.v2 import search as module
from onyx.agents.v2.models import ExecutionContext
from onyx.context.search.models import PersonaSearchInfo, SearchDocsResponse
from onyx.db.models import User
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.llm.interfaces import LLM
from onyx.tools.models import ToolResponse


@pytest.mark.parametrize("query", [None, "  postmortem follow-up actions  "])
def test_record_query_preserves_task_acl_and_existing_selection(monkeypatch, query):
    captured = {}

    class Search:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, **kwargs):
            captured["override"] = kwargs["override_kwargs"]
            return ToolResponse(
                llm_facing_response="evidence",
                rich_response=SearchDocsResponse(
                    search_docs=[], displayed_docs=[], citation_mapping={}
                ),
            )

    monkeypatch.setattr(module, "SearchTool", Search)
    tool = module.InternalSearchAnswer(
        tool_id=1,
        user=cast(User, SimpleNamespace(id="test")),
        persona=PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        ),
        filters=None,
        index=cast(DocumentIndex, object()),
        llm=cast(LLM, object()),
        task_anchor=True,
        hierarchical_selection=True,
        feedback="navigation",
        record_queries=True,
    )
    context = ExecutionContext(
        run_id="test",
        task="Count primary records",
        remaining_seconds=120,
        remaining_tokens=10000,
        cancelled=lambda: False,
    )
    args = {"objective": "Find missing primary records"}
    if query is not None:
        args["record_query"] = query
    tool.run(args, context)
    assert captured["bypass_acl"] is False
    assert captured["record_query"] == (query.strip() if query else None)
    assert captured["override"].skip_query_expansion is bool(query)
    assert captured["override"].original_query == context.task
    assert captured["override"].num_hits == 100
    assert captured["final_selection_limit"] == 10


def test_record_query_schema_bounds():
    with pytest.raises(ValueError):
        module.RecordObjective(objective="Find records", record_query="x" * 257)
