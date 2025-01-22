from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_message_runs
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionState,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    QACheckUpdate,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.prompts import SUB_CHECK_NO
from onyx.agents.agent_search.shared_graph_utils.prompts import SUB_CHECK_PROMPT
from onyx.agents.agent_search.shared_graph_utils.prompts import UNKNOWN_ANSWER


def answer_check(state: AnswerQuestionState, config: RunnableConfig) -> QACheckUpdate:
    if state.answer == UNKNOWN_ANSWER:
        return QACheckUpdate(
            answer_quality=SUB_CHECK_NO,
        )
    msg = [
        HumanMessage(
            content=SUB_CHECK_PROMPT.format(
                question=state.question,
                base_answer=state.answer,
            )
        )
    ]

    agent_searchch_config = cast(AgentSearchConfig, config["metadata"]["config"])
    fast_llm = agent_searchch_config.fast_llm
    response = list(
        fast_llm.stream(
            prompt=msg,
        )
    )

    quality_str = merge_message_runs(response, chunk_separator="")[0].content

    return QACheckUpdate(
        answer_quality=quality_str,
    )
