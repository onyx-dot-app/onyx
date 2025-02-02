from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_message_runs
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.operations import (
    dispatch_subquery,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    QueryExpansionUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.prompts.agent_search import (
    QUERY_REWRITING_PROMPT,
)


def expand_queries(
    state: ExpandedRetrievalInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> QueryExpansionUpdate:
    # Sometimes we want to expand the original question, sometimes we want to expand a sub-question.
    # When we are running this node on the original question, no question is explictly passed in.
    # Instead, we use the original question from the search request.
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    node_start_time = datetime.now()
    question = state.question

    llm = graph_config.tooling.fast_llm
    sub_question_id = state.sub_question_id
    if sub_question_id is None:
        level, question_num = 0, 0
    else:
        level, question_num = parse_question_id(sub_question_id)

    msg = [
        HumanMessage(
            content=QUERY_REWRITING_PROMPT.format(question=question),
        )
    ]

    llm_response_list = dispatch_separated(
        llm.stream(prompt=msg), dispatch_subquery(level, question_num, writer)
    )

    llm_response = merge_message_runs(llm_response_list, chunk_separator="")[0].content

    rewritten_queries = llm_response.split("\n")

    return QueryExpansionUpdate(
        expanded_queries=rewritten_queries,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="shared - expanded retrieval",
                node_name="expand queries",
                node_start_time=node_start_time,
                result=f"Number of expanded queries: {len(rewritten_queries)}",
            )
        ],
    )
