import json
from collections.abc import Sequence

from agents import function_tool
from agents import RunContextWrapper
from pydantic import BaseModel

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.agents.agent_search.dr.sub_agents.web_search.models import WebSearchResult
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    get_default_provider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    WebSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_content,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_search_result,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    llm_doc_from_web_content,
)
from onyx.chat.models import LlmDoc
from onyx.chat.turn.models import ChatTurnContext
from onyx.db.tools import get_tool_by_name
from onyx.server.query_and_chat.streaming_models import FetchToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SavedSearchDoc
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting
from onyx.utils.threadpool_concurrency import run_functions_in_parallel


class WebSearchResponse(BaseModel):
    results: Sequence[WebSearchResult]


@tool_accounting
def _web_search_core(
    run_context: RunContextWrapper[ChatTurnContext],
    queries: list[str],
    search_provider: WebSearchProvider,
) -> WebSearchResponse:
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
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=SearchToolDelta(
                type="internal_search_tool_delta", queries=queries, documents=[]
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

    # Convert hits to WebSearchResult objects
    results = []
    for r in all_hits:
        results.append(
            WebSearchResult(
                title=r.title,
                link=r.link,
                snippet=r.snippet or "",
                author=r.author,
                published_date=r.published_date,
            )
        )

    # Create inference sections from search results and add to cited documents
    inference_sections = [
        dummy_inference_section_from_internet_search_result(r) for r in all_hits
    ]

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
    return WebSearchResponse(results=results)


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
    return response.model_dump_json()


# TODO: Make a ToolV2 class to encapsulate all of this
WEB_SEARCH_LONG_DESCRIPTION = """
### Decision boundary
- You MUST call this tool to discover sources when the request involves:
    - Fresh/unstable info (news, prices, laws, schedules, product specs, scores, exchange rates).
    - Recommendations, or any query where the specific sources matter.
    - Verifiable claims, quotes, or citations.
- After ANY successful `web_search` call that yields candidate URLs, you MUST call
    `open_url` on the selected URLs BEFORE answering. Do NOT answer from snippets.

### When NOT to use
- Casual chat, rewriting/summarizing user-provided text, or translation.
- When the user already provided URLs (go straight to `open_url`).

### Usage hints
- Expand the users's query into a broader list of queries.
- Batch a list of natural-language queries per call.
- Prefer searches for distinct intents; then batch-fetch best URLs.
- Deduplicate domains/near-duplicates. Prefer recent, authoritative sources.
"""


@tool_accounting
def _open_url_core(
    run_context: RunContextWrapper[ChatTurnContext],
    urls: Sequence[str],
    search_provider: WebSearchProvider,
) -> list[LlmDoc]:
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

    docs = search_provider.contents(urls)
    llm_docs = [llm_doc_from_web_content(d) for d in docs]
    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan="plan",
            purpose="Fetching content from URLs",
            reasoning=f"I am now using Web Fetch to gather information on {', '.join(urls)}",
        )
    )
    run_context.context.unordered_fetched_inference_sections.extend(
        [dummy_inference_section_from_internet_content(d) for d in docs]
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

    return llm_docs


@function_tool
def open_url(
    run_context: RunContextWrapper[ChatTurnContext], urls: Sequence[str]
) -> str:
    """
    Tool for fetching and extracting full content from web pages.
    """
    search_provider = get_default_provider()
    if search_provider is None:
        raise ValueError("No search provider found")
    retrieved_docs = _open_url_core(run_context, urls, search_provider)
    return json.dumps([doc.model_dump(mode="json") for doc in retrieved_docs])


# TODO: Make a ToolV2 class to encapsulate all of this
OPEN_URL_LONG_DESCRIPTION = """
### Decision boundary
- You MUST use this tool before quoting, citing, or relying on page content.
- Use it whenever you already have URLs (from the user or from `web_search`).
- Do NOT answer questions based on search snippets alone.
- After a web_search call, strong bias towards using this tool to investigate further.

### When NOT to use
- If you do not yet have URLs (search first).

### Usage hints
- If you've just called web_search, be generous with the number of URLs you fetch.
- Avoid many tiny calls; batch URLs in one request.
- Prefer primary, recent, and reputable sources.
- If PDFs/long docs appear, still fetch; you may summarize sections explicitly.
"""
