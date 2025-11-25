from typing import cast

from agents import function_tool
from agents import RunContextWrapper
from pydantic import TypeAdapter

from onyx.agents.agent_search.dr.models import InferenceSection
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.prune_and_merge import prune_and_merge_sections
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.turn.models import ChatTurnContext
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.tools import get_tool_by_name
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmInternalSearchResult,
)
from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel


@tool_accounting
def _internal_search_core(
    run_context: RunContextWrapper[ChatTurnContext],
    queries: list[str],
    search_tool: SearchTool,
) -> list[LlmInternalSearchResult]:
    """Core internal search logic that can be tested with dependency injection"""
    index = run_context.context.current_run_step
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolStart(
                type="internal_search_tool_start", is_internet_search=False
            ),
        )
    )
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolDelta(
                type="internal_search_tool_delta", queries=queries, documents=[]
            ),
        )
    )
    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="plan",
            purpose="Searching internally for information",
            reasoning=f"I am now using Internal Search to gather information on {queries}",
        )
    )

    def execute_single_query(
        query: str, parallelization_nr: int
    ) -> list[InferenceSection]:
        """Execute a single query and return the retrieved documents as LlmDocs"""
        retrieved_sections: list[InferenceSection] = []

        with get_session_with_current_tenant() as search_db_session:
            for tool_response in search_tool.run(
                query=query,
                override_kwargs=SearchToolOverrideKwargs(
                    force_no_rerank=True,
                    alternate_db_session=search_db_session,
                    skip_query_analysis=True,
                    original_query=query,
                ),
            ):
                if not is_connected(
                    run_context.context.chat_session_id,
                    run_context.context.run_dependencies.redis_client,
                ):
                    break
                # get retrieved docs to send to the rest of the graph
                if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                    search_response_summary = cast(
                        SearchResponseSummary, tool_response.response
                    )
                    retrieved_sections = search_response_summary.top_sections
                    break

        return retrieved_sections

    # Execute all queries in parallel using run_functions_in_parallel
    function_calls = [
        FunctionCall(func=execute_single_query, args=(query, i))
        for i, query in enumerate(queries)
    ]
    search_results_dict = run_functions_in_parallel(function_calls)

    # Aggregate all results from all queries
    all_retrieved_sections: list[InferenceSection] = []
    for result_id in search_results_dict:
        retrieved_sections = search_results_dict[result_id]
        if retrieved_sections:
            all_retrieved_sections.extend(retrieved_sections)

    # Use the current input token count from context for pruning
    # This includes system prompt, history, user message, and any agent turns so far
    existing_input_tokens = run_context.context.current_input_tokens

    pruned_sections: list[InferenceSection] = prune_and_merge_sections(
        sections=all_retrieved_sections,
        section_relevance_list=None,
        llm_config=search_tool.llm.config,
        existing_input_tokens=existing_input_tokens,
        contextual_pruning_config=search_tool.contextual_pruning_config,
    )

    search_results_for_query = [
        LlmInternalSearchResult(
            document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            title=section.center_chunk.semantic_identifier,
            excerpt=section.combined_content,
            metadata=section.center_chunk.metadata,
            unique_identifier_to_strip_away=section.center_chunk.document_id,
        )
        for section in pruned_sections
    ]

    from onyx.chat.turn.models import FetchedDocumentCacheEntry

    for section in pruned_sections:
        unique_id = section.center_chunk.document_id
        if unique_id not in run_context.context.fetched_documents_cache:
            run_context.context.fetched_documents_cache[unique_id] = (
                FetchedDocumentCacheEntry(
                    inference_section=section,
                    document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                )
            )

    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolDelta(
                type="internal_search_tool_delta",
                queries=[],
                documents=convert_inference_sections_to_search_docs(
                    pruned_sections, is_internet=False
                ),
            ),
        )
    )
    run_context.context.global_iteration_responses.append(
        IterationAnswer(
            tool=SearchTool.__name__,
            tool_id=get_tool_by_name(
                SearchTool.__name__,
                run_context.context.run_dependencies.db_session,
            ).id,
            iteration_nr=index,
            parallelization_nr=0,
            question=queries[0] if queries else "",
            reasoning=f"I am now using Internal Search to gather information on {queries[0] if queries else ''}",
            answer="",
            cited_documents={
                i: inference_section
                for i, inference_section in enumerate(pruned_sections)
            },
            queries=queries,
        )
    )
    # Set flag to include citation requirements since we retrieved documents
    run_context.context.should_cite_documents = (
        run_context.context.should_cite_documents or bool(pruned_sections)
    )

    return search_results_for_query


@function_tool
def internal_search(
    run_context: RunContextWrapper[ChatTurnContext], queries: list[str]
) -> str:
    """
    Tool for searching over the user's internal knowledge base.
    """
    search_pipeline_instance = next(
        (
            tool
            for tool in run_context.context.run_dependencies.tools
            if tool.name == SearchTool._NAME
        ),
        None,
    )
    if search_pipeline_instance is None:
        raise ValueError("Search tool not found")

    # Call the core function
    retrieved_docs = _internal_search_core(
        run_context, queries, cast(SearchTool, search_pipeline_instance)
    )
    adapter = TypeAdapter(list[LlmInternalSearchResult])
    return adapter.dump_json(retrieved_docs).decode()
