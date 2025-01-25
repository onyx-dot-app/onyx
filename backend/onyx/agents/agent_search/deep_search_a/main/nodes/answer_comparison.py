from datetime import datetime
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import AnswerComparison
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.prompts import ANSWER_COMPARISON_PROMPT
from onyx.chat.models import RefinedAnswerImprovement


def answer_comparison(state: MainState, config: RunnableConfig) -> AnswerComparison:
    now_start = datetime.now()

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = agent_a_config.search_request.query
    initial_answer = state.initial_answer
    refined_answer = state.refined_answer

    logger.debug(f"--------{now_start}--------ANSWER COMPARISON STARTED--")

    answer_comparison_prompt = ANSWER_COMPARISON_PROMPT.format(
        question=question, initial_answer=initial_answer, refined_answer=refined_answer
    )

    msg = [HumanMessage(content=answer_comparison_prompt)]

    # Get the rewritten queries in a defined format
    model = agent_a_config.fast_llm

    # no need to stream this
    resp = model.invoke(msg)

    refined_answer_improvement = (
        isinstance(resp.content, str) and "yes" in resp.content.lower()
    )

    dispatch_custom_event(
        "refined_answer_improvement",
        RefinedAnswerImprovement(
            refined_answer_improvement=refined_answer_improvement,
        ),
    )

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------ANSWER COMPARISON COMPLETED---"
    )

    return AnswerComparison(
        refined_answer_improvement=refined_answer_improvement,
        log_messages=[
            f"{now_start} -- Answer comparison: {refined_answer_improvement},  Time taken: {now_end - now_start}"
        ],
    )
