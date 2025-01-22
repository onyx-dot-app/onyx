from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.deep_search_a.main.states import (
    RequireRefinedAnswerUpdate,
)
from onyx.agents.agent_search.models import AgentSearchConfig


def refined_answer_decision(
    state: MainState, config: RunnableConfig
) -> RequireRefinedAnswerUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------REFINED ANSWER DECISION---")

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    if "?" in agent_a_config.search_request.query:
        decision = False
    else:
        decision = True

    decision = True

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------REFINED ANSWER DECISION END---"
    )

    if agent_a_config.allow_refinement:
        return RequireRefinedAnswerUpdate(require_refined_answer=decision)

    else:
        return RequireRefinedAnswerUpdate(require_refined_answer=False)
