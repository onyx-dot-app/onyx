from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search_a.main.states import AnswerComparison
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.prompts import ANSWER_COMPARISON_PROMPT
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import RefinedAnswerImprovement


def compare_answers(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> AnswerComparison:
    node_start_time = datetime.now()

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = agent_a_config.search_request.query
    initial_answer = state.initial_answer
    refined_answer = state.refined_answer

    compare_answers_prompt = ANSWER_COMPARISON_PROMPT.format(
        question=question, initial_answer=initial_answer, refined_answer=refined_answer
    )

    msg = [HumanMessage(content=compare_answers_prompt)]

    # Get the rewritten queries in a defined format
    model = agent_a_config.fast_llm

    # no need to stream this
    resp = model.invoke(msg)

    refined_answer_improvement = (
        isinstance(resp.content, str) and "yes" in resp.content.lower()
    )

    write_custom_event(
        "refined_answer_improvement",
        RefinedAnswerImprovement(
            refined_answer_improvement=refined_answer_improvement,
        ),
        writer,
    )

    return AnswerComparison(
        refined_answer_improvement_eval=refined_answer_improvement,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="compare answers",
                node_start_time=node_start_time,
                result=f"Answer comparison: {refined_answer_improvement}",
            )
        ],
    )
