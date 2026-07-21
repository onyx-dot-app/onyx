"""External-dependency-unit tests for the internal_search → paginate_search_results
flow: search-query-id issuance, the in-memory result cache, page windows, idempotent
re-serving, and the OpenSearch offset fallback.

Retrieval is mocked via use_mock_search_pipeline; the LLM-driven relevance
selection / context expansion steps are stubbed so no live LLM is needed.
"""

import json
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.chat.emitter import NullEmitter
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import PersonaSearchInfo
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import PaginateSearchResultsOverrideKwargs
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.models import ToolCallException
from onyx.tools.tool_implementations.search.paginate_search_results_tool import (
    PaginateSearchResultsTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.search.turn_state import SearchToolTurnState
from tests.external_dependency_unit.mock_search_pipeline import MockInternalSearchResult
from tests.external_dependency_unit.mock_search_pipeline import use_mock_search_pipeline

SEARCH_TOOL_MODULE = "onyx.tools.tool_implementations.search.search_tool"

PAGE_SIZE = 5
QUERY = "what is the Q2 strategy?"


def _make_results(count: int, prefix: str = "doc") -> list[MockInternalSearchResult]:
    """Distinct document ids so chunk merging keeps sections 1:1 with chunks."""
    return [
        MockInternalSearchResult(
            document_id=f"{prefix}_{i}",
            source_type=DocumentSource.CONFLUENCE,
            semantic_identifier=f"{prefix} {i}",
            chunk_ind=0,
        )
        for i in range(count)
    ]


def _make_tools() -> tuple[SearchTool, PaginateSearchResultsTool]:
    turn_state = SearchToolTurnState()
    emitter = NullEmitter()
    user = MagicMock(is_anonymous=False)
    persona_search_info = PersonaSearchInfo(
        document_set_names=[],
        search_start_date=None,
        attached_document_ids=[],
        hierarchy_node_ids=[],
    )
    llm = MagicMock()
    document_index = MagicMock()
    search_tool = SearchTool(
        tool_id=1,
        emitter=emitter,
        user=user,
        persona_search_info=persona_search_info,
        llm=llm,
        document_index=document_index,
        user_selected_filters=None,
        project_id_filter=None,
        enable_slack_search=False,
        turn_state=turn_state,
    )
    paginate_tool = PaginateSearchResultsTool(
        tool_id=1,
        emitter=emitter,
        user=user,
        persona_search_info=persona_search_info,
        llm=llm,
        document_index=document_index,
        turn_state=turn_state,
    )
    return search_tool, paginate_tool


@contextmanager
def _stub_post_retrieval_llm_steps() -> Generator[None, None, None]:
    """Stub the LLM relevance-selection and context-expansion steps so every
    section in the window passes through unchanged."""

    def select_all(sections: list[Any], **_: Any) -> tuple[list[Any], list[str]]:
        return sections, []

    def expand_identity(section: Any, **_: Any) -> Any:
        return section

    with (
        patch(f"{SEARCH_TOOL_MODULE}.select_sections_for_expansion", select_all),
        patch(f"{SEARCH_TOOL_MODULE}.expand_section_with_context", expand_identity),
        patch(
            f"{SEARCH_TOOL_MODULE}.get_llm_token_counter",
            return_value=lambda _text: 1,
        ),
    ):
        yield


def _run_search(search_tool: SearchTool, num_results_expected: int) -> dict[str, Any]:
    response = search_tool.run(
        placement=Placement(turn_index=0, tab_index=0),
        override_kwargs=SearchToolOverrideKwargs(
            starting_citation_num=1,
            original_query=None,
            skip_query_expansion=True,
            num_hits=PAGE_SIZE,
        ),
        semantic_queries=[QUERY],
    )
    payload = json.loads(response.llm_facing_response)
    assert len(payload["results"]) == num_results_expected
    return payload


def _run_paginate(
    paginate_tool: PaginateSearchResultsTool, search_query_id: int, page: int
) -> dict[str, Any]:
    response = paginate_tool.run(
        placement=Placement(turn_index=1, tab_index=0),
        override_kwargs=PaginateSearchResultsOverrideKwargs(
            starting_citation_num=101,
            num_hits=PAGE_SIZE,
        ),
        search_query_id=search_query_id,
        page=page,
    )
    return json.loads(response.llm_facing_response)


def test_search_then_paginate_serves_next_windows() -> None:
    search_tool, paginate_tool = _make_tools()
    results = _make_results(12)

    with use_mock_search_pipeline([DocumentSource.CONFLUENCE]) as controller:
        controller.add_search_results(QUERY, results)
        with _stub_post_retrieval_llm_steps():
            search_payload = _run_search(search_tool, num_results_expected=PAGE_SIZE)

            assert search_payload["search_query_id"] == 1
            assert "page" not in search_payload
            page_0_titles = {r["title"] for r in search_payload["results"]}

            page_1 = _run_paginate(paginate_tool, search_query_id=1, page=1)
            assert page_1["search_query_id"] == 1
            assert page_1["page"] == 1
            page_1_titles = {r["title"] for r in page_1["results"]}
            assert len(page_1["results"]) == PAGE_SIZE
            assert page_0_titles.isdisjoint(page_1_titles)

            # Page 2: only 2 sections remain in the cache. The fallback re-query
            # returns the same 12 results (the mock ignores offsets), so dedup
            # finds nothing new and the search latches exhausted.
            page_2 = _run_paginate(paginate_tool, search_query_id=1, page=2)
            assert page_2["page"] == 2
            page_2_titles = {r["title"] for r in page_2["results"]}
            assert len(page_2["results"]) == 2
            assert page_2_titles.isdisjoint(page_0_titles | page_1_titles)

            # Page 3: nothing left — empty results with a note.
            page_3 = _run_paginate(paginate_tool, search_query_id=1, page=3)
            assert page_3["results"] == []
            assert "No further results" in page_3["note"]


def test_paginate_is_idempotent_per_page() -> None:
    search_tool, paginate_tool = _make_tools()

    with use_mock_search_pipeline([DocumentSource.CONFLUENCE]) as controller:
        controller.add_search_results(QUERY, _make_results(12))
        with _stub_post_retrieval_llm_steps():
            _run_search(search_tool, num_results_expected=PAGE_SIZE)

            first = _run_paginate(paginate_tool, search_query_id=1, page=1)
            second = _run_paginate(paginate_tool, search_query_id=1, page=1)
            assert first == second


def test_paginate_page_zero_reserves_original_response() -> None:
    search_tool, paginate_tool = _make_tools()

    with use_mock_search_pipeline([DocumentSource.CONFLUENCE]) as controller:
        controller.add_search_results(QUERY, _make_results(8))
        with _stub_post_retrieval_llm_steps():
            search_payload = _run_search(search_tool, num_results_expected=PAGE_SIZE)
            page_0 = _run_paginate(paginate_tool, search_query_id=1, page=0)
            assert page_0 == search_payload


def test_unknown_search_query_id_is_llm_facing_error() -> None:
    _, paginate_tool = _make_tools()

    with pytest.raises(ToolCallException) as exc_info:
        paginate_tool.run(
            placement=Placement(turn_index=0, tab_index=0),
            override_kwargs=PaginateSearchResultsOverrideKwargs(
                starting_citation_num=1,
                num_hits=PAGE_SIZE,
            ),
            search_query_id=99,
            page=1,
        )
    assert "search_query_id" in exc_info.value.llm_facing_message


def test_search_query_ids_increment_per_search() -> None:
    search_tool, _ = _make_tools()

    with use_mock_search_pipeline([DocumentSource.CONFLUENCE]) as controller:
        controller.add_search_results(QUERY, _make_results(3))
        with _stub_post_retrieval_llm_steps():
            first = _run_search(search_tool, num_results_expected=3)
            second = _run_search(search_tool, num_results_expected=3)
            assert first["search_query_id"] == 1
            assert second["search_query_id"] == 2


def test_fallback_requeries_opensearch_with_offset() -> None:
    """When the requested page runs past the cache, the paginate tool re-runs
    the original query specs with an offset and no federated retrieval."""
    search_tool, paginate_tool = _make_tools()

    fallback_chunks = [
        result.to_inference_chunk() for result in _make_results(5, prefix="deep")
    ]
    fallback_pipeline = MagicMock(return_value=fallback_chunks)

    with use_mock_search_pipeline([DocumentSource.CONFLUENCE]) as controller:
        controller.add_search_results(QUERY, _make_results(5))
        with _stub_post_retrieval_llm_steps():
            _run_search(search_tool, num_results_expected=PAGE_SIZE)

            with patch(
                "onyx.tools.tool_implementations.search.paginate_search_results_tool"
                ".search_pipeline",
                fallback_pipeline,
            ):
                page_1 = _run_paginate(paginate_tool, search_query_id=1, page=1)

    assert fallback_pipeline.called
    request = fallback_pipeline.call_args.kwargs["chunk_search_request"]
    assert request.query == QUERY
    assert request.offset == PAGE_SIZE
    assert request.limit == PAGE_SIZE
    assert (
        fallback_pipeline.call_args.kwargs["prefetched_federated_retrieval_infos"] == []
    )

    titles = {r["title"] for r in page_1["results"]}
    assert titles == {f"deep {i}" for i in range(5)}
