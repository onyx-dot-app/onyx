import json
from typing import List

from agents import function_tool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    get_default_provider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_search_result,
)
from onyx.chat.turn.models import MyContext
from onyx.configs.constants import DocumentSource
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd


def short_tag(link: str, i: int) -> str:
    return f"S{i+1}"


@function_tool
def web_search(run_context: RunContextWrapper[MyContext], query: str) -> str:
    """
    Perform a live search on the public internet.

    Use this tool when you need fresh or external information not found
    in the conversation. It returns a ranked list of web pages with titles,
    snippets, and URLs.

    Args:
        query: The natural-language search query.
    """
    search_provider = get_default_provider()
    # TODO: Find better way to track index that isn't so implicit
    # based on number of tool calls
    index = run_context.context.current_run_step + 1
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolStart(
                type="internal_search_tool_start", is_internet_search=True
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
            purpose="Searching the web for information",
            reasoning=f"I am now using Web Search to gather information on {query}",
        )
    )
    hits = search_provider.search(query)
    results = []
    for i, r in enumerate(hits):
        results.append(
            {
                "tag": short_tag(r.link, i),
                "title": r.title,
                "link": r.link,
                "snippet": r.snippet,
                "author": r.author,
                "published_date": (
                    r.published_date.isoformat() if r.published_date else None
                ),
            }
        )
    saved_search_docs = [
        SavedSearchDoc(
            db_doc_id=0,
            document_id=hit.link,
            chunk_ind=0,
            semantic_identifier=hit.link,
            link=hit.link,
            blurb=hit.snippet,
            source_type=DocumentSource.WEB,
            boost=1,
            hidden=False,
            metadata={},
            score=0.0,
            is_relevant=None,
            relevance_explanation=None,
            match_highlights=[],
            updated_at=None,
            primary_owners=None,
            secondary_owners=None,
            is_internet=True,
        )
        for hit in hits
    ]
    # TODO: Remove "Results" section from internet search tool
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolDelta(
                type="internal_search_tool_delta",
                queries=None,
                documents=saved_search_docs,
            ),
        )
    )
    dummy_docs_inference_sections = [
        dummy_inference_section_from_internet_search_result(doc) for doc in hits
    ]
    run_context.context.aggregated_context.global_iteration_responses.append(
        IterationAnswer(
            tool="web_search",
            tool_id=18,
            iteration_nr=index,
            parallelization_nr=0,
            question=query,
            reasoning=f"I am now using Web Search to gather information on {query}",
            answer="Cool",
            cited_documents={
                i: inference_section
                for i, inference_section in enumerate(dummy_docs_inference_sections)
            },
        )
    )
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SectionEnd(
                type="section_end",
            ),
        )
    )
    run_context.context.current_run_step = index + 1
    return json.dumps({"results": results})


@function_tool
def web_fetch(run_context: RunContextWrapper[MyContext], urls: List[str]) -> str:
    """
    Fetch and extract the text content from a specific web page.

    Use this tool after identifying relevant URLs (for example from
    `web_search`) to read the full content. It returns the cleaned page
    text and metadata.

    Args:
        urls: The full URLs of the pages to retrieve.
    """
    search_provider = get_default_provider()
    docs = search_provider.contents(urls)
    out = []
    for i, d in enumerate(docs):
        out.append(
            {
                "tag": short_tag(d.link, i),  # <-- add a tag
                "title": d.title,
                "link": d.link,
                "full_content": d.full_content,
                "published_date": (
                    d.published_date.isoformat() if d.published_date else None
                ),
            }
        )
    # TODO: Emit event for web search "reading" URL
    return json.dumps({"results": out})
