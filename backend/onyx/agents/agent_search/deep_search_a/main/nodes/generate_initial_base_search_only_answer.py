from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import InitialAnswerBASEUpdate
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import INITIAL_RAG_BASE_PROMPT
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs


def generate_initial_base_search_only_answer(
    state: MainState,
    config: RunnableConfig,
) -> InitialAnswerBASEUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE INITIAL BASE ANSWER---")

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = agent_a_config.search_request.query
    original_question_docs = state.all_original_question_documents

    model = agent_a_config.fast_llm

    doc_context = format_docs(original_question_docs)
    doc_context = trim_prompt_piece(
        model.config, doc_context, INITIAL_RAG_BASE_PROMPT + question
    )

    msg = [
        HumanMessage(
            content=INITIAL_RAG_BASE_PROMPT.format(
                question=question,
                context=doc_context,
            )
        )
    ]

    # Grader
    response = model.invoke(msg)
    answer = response.pretty_repr()

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL BASE ANSWER END---\n\n"
    )

    return InitialAnswerBASEUpdate(initial_base_answer=answer)
