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
    seen_urls = set()
    deduped_urls_to_open = []
    for query, url in state.urls_to_open:
        if url not in seen_urls:
            seen_urls.add(url)
            deduped_urls_to_open.append((query, url))
    deduped_branch_question_to_urls: dict[str, list[str]] = {}
    for query, url in deduped_urls_to_open:
        deduped_branch_question_to_urls.setdefault(query, []).append(url)

    return InternetSearchInput(
        urls_to_open=[],
        parallelization_nr=state.parallelization_nr,
        branch_question=state.branch_question,
        deduped_branch_question_to_urls=deduped_branch_question_to_urls,
    )
