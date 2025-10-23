from typing import cast

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import InferenceSection
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.chat.models import LlmDoc
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
from onyx.tools.tool_implementations.search.search_utils import section_to_llm_doc
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel


@tool_accounting
def _internal_search_core(
    run_context: RunContextWrapper[ChatTurnContext],
    queries: list[str],
    search_tool: SearchTool,
) -> list[LlmDoc]:
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

    def execute_single_query(query: str, parallelization_nr: int) -> list[LlmDoc]:
        """Execute a single query and return the retrieved documents as LlmDocs"""
        retrieved_llm_docs_for_query: list[LlmDoc] = []

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
                    # TODO: just a heuristic to not overload context window -- carried over from existing DR flow
                    docs_to_feed_llm = 15
                    retrieved_sections: list[InferenceSection] = response.top_sections[
                        :docs_to_feed_llm
                    ]

                    # Convert InferenceSections to LlmDocs for return value
                    retrieved_llm_docs_for_query = [
                        section_to_llm_doc(section) for section in retrieved_sections
                    ]

                    run_context.context.run_dependencies.emitter.emit(
                        Packet(
                            ind=index,
                            obj=SearchToolDelta(
                                type="internal_search_tool_delta",
                                queries=[],
                                documents=convert_inference_sections_to_search_docs(
                                    retrieved_sections, is_internet=False
                                ),
                            ),
                        )
                    )
                    run_context.context.aggregated_context.cited_documents.extend(
                        retrieved_sections
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
                                for i, inference_section in enumerate(
                                    retrieved_sections
                                )
                            },
                            queries=[query],
                        )
                    )
                    break

        return retrieved_llm_docs_for_query

    # Execute all queries in parallel using run_functions_in_parallel
    function_calls = [
        FunctionCall(func=execute_single_query, args=(query, i))
        for i, query in enumerate(queries)
    ]
    search_results_dict = run_functions_in_parallel(function_calls)

    # Aggregate all results from all queries
    all_retrieved_docs: list[LlmDoc] = []
    for result_id in search_results_dict:
        retrieved_docs = search_results_dict[result_id]
        if retrieved_docs:
            all_retrieved_docs.extend(retrieved_docs)

    # Set flag to include citation requirements since we retrieved documents
    run_context.context.should_cite_documents = (
        run_context.context.should_cite_documents or bool(all_retrieved_docs)
    )

    return all_retrieved_docs


@function_tool
def internal_search(
    run_context: RunContextWrapper[ChatTurnContext], queries: list[str]
) -> str:
    """
    Tool for searching over internal knowledge base from the user's connectors.
    The queries will be searched over a vector database where a hybrid search will be performed.
    Will return a combination of keyword and semantic search results.
    ---
    ## Decision boundary
    - MUST call this tool if the user's query requires internal information, like
    if it references "we" or "us" or "our" or "internal" or if it references
    the organization the user works for.
    - MUST call this tool if the user's query sounds like the name of a specific internal document,
    like some keyword that could be a document name.

    ## Usage hints
    - Batch a list of natural-language queries per call.
    - Generally try searching with some semantic queries and some keyword queries
    to give the hybrid search the best chance of finding relevant results.

    ## Args
    - queries (list[str]): The search queries.

    ## Returns (list of LlmDoc objects as string)
    Each LlmDoc contains:
    - document_id: Unique document identifier
    - content: Full document content (combined from all chunks in the section)
    - blurb: Text excerpt from the document
    - semantic_identifier: Human-readable document name
    - source_type: Type of document source (e.g., web, confluence, etc.)
    - metadata: Additional document metadata
    - updated_at: When document was last updated
    - link: Primary URL to the source (may be None). Used for citations.
    - source_links: Dictionary of URLs to the source
    - match_highlights: Highlighted matching text snippets
    """
    search_pipeline_instance = run_context.context.run_dependencies.search_pipeline
    if search_pipeline_instance is None:
        raise RuntimeError("Search tool not available in context")

    # Call the core function
    retrieved_docs = _internal_search_core(
        run_context, queries, search_pipeline_instance
    )

    return str(retrieved_docs)
