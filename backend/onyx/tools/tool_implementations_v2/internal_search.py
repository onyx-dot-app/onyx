from typing import cast

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.turn.models import MyContext
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary


@function_tool
def internal_search(run_context: RunContextWrapper[MyContext], query: str) -> str:
    """
    Search the internal knowledge base and documents.

    Use this tool when the answer is likely stored in private or company
    documents rather than on the public web. It returns snippets, titles,
    and links to relevant internal files.

    Args:
        query: The natural-language search query.
    """
    search_tool = run_context.context.run_dependencies.search_tool
    if search_tool is None:
        raise RuntimeError("Search tool not available in context")

    index = run_context.context.current_run_step + 1
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
        for tool_response in search_tool.run(
            query=query,
            override_kwargs=SearchToolOverrideKwargs(
                force_no_rerank=True,
                alternate_db_session=search_db_session,
                skip_query_analysis=True,
                original_query=query,
            ),
        ):
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
                run_context.context.aggregated_context.global_iteration_responses.append(
                    IterationAnswer(
                        tool="internal_search",
                        tool_id=1,
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
                break
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SectionEnd(
                type="section_end",
            ),
        )
    )
    run_context.context.current_run_step = index + 1
    return retrieved_docs
