from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.internet_search.states import (
    InternetSearchInput,
)


def dedup_urls(
    state: InternetSearchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> InternetSearchInput:
    urls_to_open = state.urls_to_open
    url_set = set()
    deduped_urls_to_open = []
    for query, url in urls_to_open:
        if url not in url_set:
            url_set.add(url)
            deduped_urls_to_open.append((query, url))
    deduped_branch_question_to_urls: dict[str, list[str]] = {}
    for query, url in deduped_urls_to_open:
        if query not in deduped_branch_question_to_urls:
            deduped_branch_question_to_urls[query] = []
        deduped_branch_question_to_urls[query].append(url)
    return InternetSearchInput(
        urls_to_open=[],
        parallelization_nr=state.parallelization_nr,
        branch_question=state.branch_question,
        deduped_branch_question_to_urls=deduped_branch_question_to_urls,
    )
