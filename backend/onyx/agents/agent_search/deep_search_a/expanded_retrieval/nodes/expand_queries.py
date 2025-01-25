from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_message_runs
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.operations import (
    dispatch_subquery,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    QueryExpansionUpdate,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    REWRITE_PROMPT_MULTI_ORIGINAL,
)
from onyx.agents.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id


def expand_queries(
    state: ExpandedRetrievalInput, config: RunnableConfig
) -> QueryExpansionUpdate:
    # Sometimes we want to expand the original question, sometimes we want to expand a sub-question.
    # When we are running this node on the original question, no question is explictly passed in.
    # Instead, we use the original question from the search request.
    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    now_start = datetime.now()
    question = (
        state.question
        if hasattr(state, "question")
        else agent_a_config.search_request.query
    )
    llm = agent_a_config.fast_llm
    chat_session_id = agent_a_config.chat_session_id
    sub_question_id = state.sub_question_id
    if sub_question_id is None:
        level, question_nr = 0, 0
    else:
        level, question_nr = parse_question_id(sub_question_id)

    if chat_session_id is None:
        raise ValueError("chat_session_id must be provided for agent search")

    msg = [
        HumanMessage(
            content=REWRITE_PROMPT_MULTI_ORIGINAL.format(question=question),
        )
    ]

    llm_response_list = dispatch_separated(
        llm.stream(prompt=msg), dispatch_subquery(level, question_nr)
    )

    llm_response = merge_message_runs(llm_response_list, chunk_separator="")[0].content

    rewritten_queries = llm_response.split("\n")
    now_end = datetime.now()
    return QueryExpansionUpdate(
        expanded_queries=rewritten_queries,
        log_messages=[
            f"{now_end} -- Expanded Retrieval - Query Expansion - Time taken: {now_end - now_start}"
        ],
    )
