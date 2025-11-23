from collections.abc import Sequence

from agents import function_tool
from agents import RunContextWrapper
from pydantic import TypeAdapter

from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import FetchedDocumentCacheEntry
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.server.query_and_chat.streaming_models import OpenUrl
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDocumentsDelta
from onyx.server.query_and_chat.streaming_models import SearchToolQueriesDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.tool_implementations.web_search.models import WebContentProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.providers import (
    get_default_content_provider,
)
from onyx.tools.tool_implementations.web_search.providers import get_default_provider
from onyx.tools.tool_implementations.web_search.utils import (
    dummy_inference_section_from_internet_content,
)
from onyx.tools.tool_implementations.web_search.utils import (
    dummy_inference_section_from_internet_search_result,
)
from onyx.tools.tool_implementations.web_search.utils import (
    truncate_search_result_content,
)
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.tools.tool_implementations_v2.tool_result_models import LlmOpenUrlResult
from onyx.tools.tool_implementations_v2.tool_result_models import LlmWebSearchResult
from onyx.utils.threadpool_concurrency import run_functions_in_parallel


@tool_accounting
def _web_search_core(
    run_context: RunContextWrapper[ChatTurnContext],
    queries: list[str],
    search_provider: WebSearchProvider,
) -> list[LlmWebSearchResult]:
    from onyx.utils.threadpool_concurrency import FunctionCall

    index = run_context.context.current_run_step
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            turn_index=index,
            tab_index=None,
            obj=SearchToolStart(type="search_tool_start", is_internet_search=True),
        )
    )

    # Emit a packet in the beginning to communicate queries to the frontend
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            turn_index=index,
            tab_index=None,
            obj=SearchToolQueriesDelta(
                queries=queries,
            ),
        )
    )

    ", ".join(queries)

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

    saved_search_docs = convert_inference_sections_to_search_docs(
        inference_sections, is_internet=True
    )

    run_context.context.run_dependencies.emitter.emit(
        Packet(
            turn_index=index,
            tab_index=0,
            obj=SearchToolDocumentsDelta(
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


@tool_accounting
def _open_url_core(
    run_context: RunContextWrapper[ChatTurnContext],
    urls: Sequence[str],
    content_provider: WebContentProvider,
) -> list[LlmOpenUrlResult]:
    # TODO: Find better way to track index that isn't so implicit
    # based on number of tool calls
    index = run_context.context.current_run_step

    # Create SavedSearchDoc objects from URLs for the OpenUrlStart event
    saved_search_docs = [SavedSearchDoc.from_url(url) for url in urls]

    run_context.context.run_dependencies.emitter.emit(
        Packet(
            turn_index=index,
            tab_index=None,
            obj=OpenUrl(documents=saved_search_docs),
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
