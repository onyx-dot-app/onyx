from typing import cast

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
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
from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel


@tool_accounting
def _internal_search_core(
    run_context: RunContextWrapper[ChatTurnContext],
    queries: list[str],
    search_tool: SearchTool,
) -> list:
    """Core internal search logic that can be tested with dependency injection"""
    if search_tool is None:
        raise RuntimeError("Search tool not available in context")

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
                type="internal_search_tool_delta", queries=queries, documents=None
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

    def execute_single_query(query: str, parallelization_nr: int) -> list:
        """Execute a single query and return the retrieved documents"""
        retrieved_docs_for_query: list = []

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
                    response = cast(SearchResponseSummary, tool_response.response)
                    retrieved_docs = response.top_sections
                    retrieved_docs_for_query = retrieved_docs

                    run_context.context.run_dependencies.emitter.emit(
                        Packet(
                            ind=index,
                            obj=SearchToolDelta(
                                type="internal_search_tool_delta",
                                queries=None,
                                documents=convert_inference_sections_to_search_docs(
                                    retrieved_docs, is_internet=False
                                ),
                            ),
                        )
                    )
                    run_context.context.aggregated_context.cited_documents.extend(
                        retrieved_docs
                    )
                    run_context.context.aggregated_context.global_iteration_responses.append(
                        IterationAnswer(
                            tool=SearchTool.__name__,
                            tool_id=get_tool_by_name(
                                SearchTool.__name__,
                                run_context.context.run_dependencies.db_session,
                            ).id,
                            iteration_nr=index,
                            parallelization_nr=parallelization_nr,
                            question=query,
                            reasoning=f"I am now using Internal Search to gather information on {query}",
                            answer="",
                            cited_documents={
                                i: inference_section
                                for i, inference_section in enumerate(retrieved_docs)
                            },
                        )
                    )
                    break

        return retrieved_docs_for_query

    # Execute all queries in parallel using run_functions_in_parallel
    function_calls = [
        FunctionCall(func=execute_single_query, args=(query, i))
        for i, query in enumerate(queries)
    ]
    search_results_dict = run_functions_in_parallel(function_calls)

    # Aggregate all results from all queries
    all_retrieved_docs: list = []
    for result_id in search_results_dict:
        retrieved_docs = search_results_dict[result_id]
        if retrieved_docs:
            all_retrieved_docs.extend(retrieved_docs)

    return all_retrieved_docs


@function_tool
def internal_search_tool(
    run_context: RunContextWrapper[ChatTurnContext], queries: list[str]
) -> str:
    """
    Tool for searching over internal knowledge base from the user's connectors.
    The queries will be searched over a vector database where a hybrid search will be performed.
    Will return a combination of keyword and semantic search results.
    ---
    ## Usage hints
    - Batch a list of natural-language queries per call.
    - Generally try searching with some semantic queries and some keyword queries
    to give the hybrid search the best chance of finding relevant results.

    ## Args
    - queries (list[str]): The search queries.

    ## Returns (JSON string)
    [
        {
           "center_chunk": {
            "title": "...",
                "link": "...",
                "author": "...",
                "published_date": "2025-10-01T12:34:56Z"
            },
            "chunks": [
                {
                    "content": "...",
                    "link": "...",
                    "author": "...",
                    "published_date": "2025-10-01T12:34:56Z"
                }
            ]
        }
    ]
    """
    search_pipeline_instance = run_context.context.run_dependencies.search_pipeline

    # Call the core function
    retrieved_docs = _internal_search_core(
        run_context, queries, search_pipeline_instance
    )

    return str(retrieved_docs)
