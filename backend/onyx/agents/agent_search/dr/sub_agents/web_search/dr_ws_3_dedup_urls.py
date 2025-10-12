from collections import defaultdict

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchResult,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.states import (
    InternetSearchInput,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_search_result,
)
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.server.query_and_chat.streaming_models import SearchToolDelta


def dedup_urls(
    state: InternetSearchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> InternetSearchInput:
    branch_questions_to_urls: dict[str, list[str]] = defaultdict(list)
    unique_results_by_link: dict[str, WebSearchResult] = {}
    for query, result in state.results_to_open:
        branch_questions_to_urls[query].append(result.link)
        if result.link not in unique_results_by_link:
            unique_results_by_link[result.link] = result

    unique_results = list(unique_results_by_link.values())
    dummy_docs_inference_sections = [
        dummy_inference_section_from_internet_search_result(doc)
        for doc in unique_results
    ]

    write_custom_event(
        state.current_step_nr,
        SearchToolDelta(
            queries=[],
            documents=convert_inference_sections_to_search_docs(
                dummy_docs_inference_sections, is_internet=True
            ),
        ),
        writer,
    )

    return InternetSearchInput(
        results_to_open=[],
        branch_questions_to_urls=branch_questions_to_urls,
    )
