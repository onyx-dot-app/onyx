from collections.abc import Sequence

from agents import function_tool
from agents import RunContextWrapper
from pydantic import TypeAdapter

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebContentProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchResult,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    get_default_content_provider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    get_default_provider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_content,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_search_result,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    truncate_search_result_content,
)
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import FetchedDocumentCacheEntry
from onyx.db.tools import get_tool_by_name
from onyx.server.query_and_chat.streaming_models import FetchToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_implementations_v2.tool_accounting import (
    tool_accounting_deprecated,
)
from onyx.tools.tool_result_models import LlmOpenUrlResult
from onyx.tools.tool_result_models import LlmWebSearchResult
from onyx.utils.threadpool_concurrency import run_functions_in_parallel


@tool_accounting_deprecated
def _web_search_core(
    run_context: RunContextWrapper[ChatTurnContext],
    queries: list[str],
    search_provider: WebSearchProvider,
) -> list[LlmWebSearchResult]:
    from onyx.utils.threadpool_concurrency import FunctionCall

    index = run_context.context.current_run_step
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolStart(
                type="internal_search_tool_start", is_internet_search=True
            ),
        )
    )

    # Emit a packet in the beginning to communicate queries to the frontend
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolDelta(
                type="internal_search_tool_delta",
                queries=queries,
                documents=[],
            ),
        )
    )

    queries_str = ", ".join(queries)
    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="plan",
            purpose="Searching the web for information",
            reasoning=f"I am now using Web Search to gather information on {queries_str}",
        )
    )

    # Search all queries in parallel
    function_calls = [
        FunctionCall(func=search_provider.search, args=(query,)) for query in queries
    ]
    search_results_dict = run_functions_in_parallel(function_calls)

    # Aggregate all results from all queries
    all_hits: list[WebSearchResult] = []
    for result_id in search_results_dict:
        hits = search_results_dict[result_id]
        if hits:
            all_hits.extend(hits)

    inference_sections = [
        dummy_inference_section_from_internet_search_result(r) for r in all_hits
    ]

    from onyx.agents.agent_search.dr.utils import (
        convert_inference_sections_to_search_docs,
    )

    saved_search_docs = convert_inference_sections_to_search_docs(
        inference_sections, is_internet=True
    )

    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolDelta(
                type="internal_search_tool_delta",
                queries=queries,
                documents=saved_search_docs,
            ),
        )
    )

    results = []
    for r in all_hits:
        results.append(
            LlmWebSearchResult(
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                url=r.link,
                title=r.title,
                snippet=r.snippet or "",
                unique_identifier_to_strip_away=r.link,
            )
        )
        if r.link not in run_context.context.fetched_documents_cache:
            run_context.context.fetched_documents_cache[r.link] = (
                FetchedDocumentCacheEntry(
                    inference_section=dummy_inference_section_from_internet_search_result(
                        r
                    ),
                    document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                )
            )

    run_context.context.global_iteration_responses.append(
        IterationAnswer(
            tool=WebSearchTool.__name__,
            tool_id=get_tool_by_name(
                WebSearchTool.__name__, run_context.context.run_dependencies.db_session
            ).id,
            iteration_nr=index,
            parallelization_nr=0,
            question=queries_str,
            reasoning=f"I am now using Web Search to gather information on {queries_str}",
            answer="",
            cited_documents={
                i: inference_section
                for i, inference_section in enumerate(inference_sections)
            },
            claims=[],
            queries=queries,
        )
    )
    run_context.context.should_cite_documents = True
    return results


@function_tool
def web_search(
    run_context: RunContextWrapper[ChatTurnContext], queries: list[str]
) -> str:
    """
    Tool for searching the public internet.
    """
    search_provider = get_default_provider()
    if search_provider is None:
        raise ValueError("No search provider found")
    response = _web_search_core(run_context, queries, search_provider)
    adapter = TypeAdapter(list[LlmWebSearchResult])
    return adapter.dump_json(response).decode()


# TODO: Make a ToolV2 class to encapsulate all of this
WEB_SEARCH_LONG_DESCRIPTION = """
Use the `web_search` tool to access up-to-date information from the web. Some examples of when to use the `web_search` tool \
include:
- Freshness: if up-to-date information on a topic could change or enhance the answer. Very important for topics that are \
changing or evolving.
- Niche Information: detailed info not widely known or understood (but that is likely found on the internet).
- Accuracy: if the cost of outdated information is high, use web sources directly.
"""


@tool_accounting_deprecated
def _open_url_core(
    run_context: RunContextWrapper[ChatTurnContext],
    urls: Sequence[str],
    content_provider: WebContentProvider,
) -> list[LlmOpenUrlResult]:
    # TODO: Find better way to track index that isn't so implicit
    # based on number of tool calls
    index = run_context.context.current_run_step

    # Create SavedSearchDoc objects from URLs for the FetchToolStart event
    saved_search_docs = [SavedSearchDoc.from_url(url) for url in urls]

    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=FetchToolStart(type="fetch_tool_start", documents=saved_search_docs),
        )
    )

    docs = content_provider.contents(urls)
    results = [
        LlmOpenUrlResult(
            document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            content=truncate_search_result_content(doc.full_content),
            unique_identifier_to_strip_away=doc.link,
        )
        for doc in docs
    ]
    for doc in docs:
        cache = run_context.context.fetched_documents_cache
        entry = cache.setdefault(
            doc.link,
            FetchedDocumentCacheEntry(
                inference_section=dummy_inference_section_from_internet_content(doc),
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            ),
        )
        entry.inference_section = dummy_inference_section_from_internet_content(doc)
    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="plan",
            purpose="Fetching content from URLs",
            reasoning=f"I am now using Web Fetch to gather information on {', '.join(urls)}",
        )
    )
    run_context.context.global_iteration_responses.append(
        IterationAnswer(
            # TODO: For now, we're using the web_search_tool_name since the web_fetch_tool_name is not a built-in tool
            tool=WebSearchTool.__name__,
            tool_id=get_tool_by_name(
                WebSearchTool.__name__, run_context.context.run_dependencies.db_session
            ).id,
            iteration_nr=index,
            parallelization_nr=0,
            question=f"Fetch content from URLs: {', '.join(urls)}",
            reasoning=f"I am now using Web Fetch to gather information on {', '.join(urls)}",
            answer="",
            cited_documents={
                i: dummy_inference_section_from_internet_content(d)
                for i, d in enumerate(docs)
            },
            claims=[],
            is_web_fetch=True,
        )
    )

    # Set flag to include citation requirements since we fetched documents
    run_context.context.should_cite_documents = True

    return results


@function_tool
def open_url(
    run_context: RunContextWrapper[ChatTurnContext], urls: Sequence[str]
) -> str:
    """
    Tool for fetching and extracting full content from web pages.
    """
    content_provider = get_default_content_provider()
    if content_provider is None:
        raise ValueError("No web content provider found")
    retrieved_docs = _open_url_core(run_context, urls, content_provider)
    adapter = TypeAdapter(list[LlmOpenUrlResult])
    return adapter.dump_json(retrieved_docs).decode()


# TODO: Make a ToolV2 class to encapsulate all of this
OPEN_URL_LONG_DESCRIPTION = """
Use the open_urls tool to read the content of one or more URLs. Use this tool to access the contents of the most promising \
web pages from your searches.
You can open many URLs at once by passing multiple URLs in the array if multiple pages seem promising. Prioritize the most \
promising pages and reputable sources.
You should almost always use open_urls after a web_search call.
"""
