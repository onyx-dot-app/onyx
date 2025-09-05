from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.web_search.states import FetchInput
from onyx.agents.agent_search.dr.sub_agents.web_search.states import (
    InternetSearchInput,
)


def collect_raw_docs(
    state: FetchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> InternetSearchInput:
    raw_documents = state.raw_documents

    return InternetSearchInput(
        raw_documents=raw_documents,
    )
