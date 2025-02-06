from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.main.states import (
    InitialRefinedAnswerComparisonUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import RefinedAnswerImprovement
from onyx.prompts.agent_search import (
    INITIAL_REFINED_ANSWER_COMPARISON_PROMPT,
)


def compare_answers(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> InitialRefinedAnswerComparisonUpdate:
    """
    LangGraph node to compare the initial answer and the refined answer and determine if the
    refined answer is sufficiently better than the initial answer.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    initial_answer = state.initial_answer
    refined_answer = state.refined_answer

    compare_answers_prompt = INITIAL_REFINED_ANSWER_COMPARISON_PROMPT.format(
        question=question, initial_answer=initial_answer, refined_answer=refined_answer
    )

    msg = [HumanMessage(content=compare_answers_prompt)]

    # Get the rewritten queries in a defined format
    model = graph_config.tooling.fast_llm

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

    return InitialRefinedAnswerComparisonUpdate(
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
