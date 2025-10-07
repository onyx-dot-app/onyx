from typing import cast

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.turn.models import ChatTurnContext
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.tools import get_tool_by_name
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting


@tool_accounting
def _internal_search_core(
    run_context: RunContextWrapper[ChatTurnContext],
    query: str,
    search_pipeline_instance,
) -> list:
    """Core internal search logic that can be tested with dependency injection"""
    if search_pipeline_instance is None:
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
                type="internal_search_tool_delta", queries=[query], documents=None
            ),
        )
    )
    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="plan",
            purpose="Searching internally for information",
            reasoning=f"I am now using Internal Search to gather information on {query}",
        )
    )

    with get_session_with_current_tenant() as search_db_session:
        for tool_response in search_pipeline_instance.run(
            query=query,
            override_kwargs=SearchToolOverrideKwargs(
                force_no_rerank=True,
                alternate_db_session=search_db_session,
                skip_query_analysis=True,
                original_query=query,
            ),
        ):
            if not is_connected(
                run_context.context.run_dependencies.dependencies_to_maybe_remove.chat_session_id,
                run_context.context.run_dependencies.redis_client,
            ):
                break
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections
                run_context.context.run_dependencies.emitter.emit(
                    Packet(
                        ind=index,
                        obj=SearchToolDelta(
                            type="internal_search_tool_delta",
                            queries=None,
                            documents=[
                                SavedSearchDoc(
                                    db_doc_id=0,
                                    document_id=doc.center_chunk.document_id,
                                    chunk_ind=0,
                                    semantic_identifier=doc.center_chunk.semantic_identifier,
                                    link=doc.center_chunk.semantic_identifier,
                                    blurb=doc.center_chunk.blurb,
                                    source_type=doc.center_chunk.source_type,
                                    boost=doc.center_chunk.boost,
                                    hidden=doc.center_chunk.hidden,
                                    metadata=doc.center_chunk.metadata,
                                    score=doc.center_chunk.score,
                                    is_relevant=doc.center_chunk.is_relevant,
                                    relevance_explanation=doc.center_chunk.relevance_explanation,
                                    match_highlights=doc.center_chunk.match_highlights,
                                    updated_at=doc.center_chunk.updated_at,
                                    primary_owners=doc.center_chunk.primary_owners,
                                    secondary_owners=doc.center_chunk.secondary_owners,
                                    is_internet=False,
                                )
                                for doc in retrieved_docs
                            ],
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
                        parallelization_nr=0,
                        question=query,
                        reasoning=f"I am now using Internal Search to gather information on {query}",
                        answer="Cool",
                        cited_documents={
                            i: inference_section
                            for i, inference_section in enumerate(retrieved_docs)
                        },
                    )
                )
                return retrieved_docs
    return []


@function_tool
def internal_search_tool(
    run_context: RunContextWrapper[ChatTurnContext], query: str
) -> str:
    """
    Tool for searching PRIVATE organizational knowledge from sources connected to the user.

    Args:
        query: The natural-language search query.
    """
    search_pipeline_instance = run_context.context.run_dependencies.search_pipeline

    # Call the core function
    retrieved_docs = _internal_search_core(run_context, query, search_pipeline_instance)

    return str(retrieved_docs)
