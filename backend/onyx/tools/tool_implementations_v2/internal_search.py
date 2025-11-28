from typing import cast

from agents import function_tool
from agents import RunContextWrapper
from pydantic import TypeAdapter

from onyx.chat.models import ContextualPruningConfig
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.prune_and_merge import prune_and_merge_sections
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.turn.models import ChatTurnContext
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import InferenceSection
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
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
    # Use current_run_step as turn_index (since we don't have turn_index in context)
    # In practice, turn_index would come from the chat turn, but for now we use current_run_step
    turn_index = run_context.context.current_run_step

    # Emit SearchToolStart packet
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            turn_index=turn_index,
            obj=SearchToolStart(is_internet_search=False),
        )
    )

    # Emit the queries early so the UI can display them immediately
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            turn_index=turn_index,
            obj=SearchToolQueriesDelta(queries=queries),
        )
    )

    def execute_single_query(
        query: str, parallelization_nr: int
    ) -> list[InferenceSection]:
        raise NotImplementedError("This is not implemented")
        """Execute a single query and return the retrieved documents as LlmDocs"""
        retrieved_sections: list[InferenceSection] = []

        # Check if still connected
        if not is_connected(
            run_context.context.chat_session_id,
            run_context.context.run_dependencies.redis_client,
        ):
            return []

        # Create a thread-safe session for this parallel execution
        db_session = search_tool._get_thread_safe_session()
        try:
            # Call search_pipeline directly to get InferenceSection objects
            top_chunks = search_pipeline(
                db_session=db_session,
                chunk_search_request=ChunkSearchRequest(
                    query=query,
                    user_selected_filters=search_tool.user_selected_filters,
                    bypass_acl=search_tool.bypass_acl,
                ),
                project_id=search_tool.project_id,
                document_index=search_tool.document_index,
                user=search_tool.user,
                persona=search_tool.persona,
            )

            merge_individual_chunks(top_chunks)

            # TODO: just a heuristic to not overload context window -- carried over from existing DR flow

            # Store sections in fetched_documents_cache
            for section in retrieved_sections:
                unique_id = section.center_chunk.document_id
                if unique_id not in run_context.context.fetched_documents_cache:
                    run_context.context.fetched_documents_cache[unique_id] = (
                        FetchedDocumentCacheEntry(
                            inference_section=section,
                            document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                        )
                    )

            # Emit the documents
            run_context.context.run_dependencies.emitter.emit(
                Packet(
                    turn_index=turn_index,
                    obj=SearchToolDocumentsDelta(
                        documents=convert_inference_sections_to_search_docs(
                            retrieved_sections, is_internet=False
                        ),
                    ),
                )
            )
        finally:
            # Always close the session to release database connections
            db_session.close()

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
        contextual_pruning_config=ContextualPruningConfig(
            max_chunks=1,
            num_chunk_multiple=1,
            is_manually_selected_docs=False,
            use_sections=True,
            using_tool_message=False,
        ),
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

    # Emit final documents delta
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            turn_index=turn_index,
            obj=SearchToolDocumentsDelta(
                documents=convert_inference_sections_to_search_docs(
                    pruned_sections, is_internet=False
                ),
            ),
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
            if tool.name == SearchTool.NAME
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
