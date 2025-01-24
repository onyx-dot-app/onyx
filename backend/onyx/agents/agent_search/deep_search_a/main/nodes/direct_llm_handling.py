from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import InitialAnswerUpdate
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_DEFAULT,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_PERSONA,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import DIRECT_LLM_PROMPT
from onyx.agents.agent_search.shared_graph_utils.utils import get_persona_prompt
from onyx.chat.models import AgentAnswerPiece


def direct_llm_handling(
    state: MainState, config: RunnableConfig
) -> InitialAnswerUpdate:
    now_start = datetime.now()

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = agent_a_config.search_request.query
    persona_prompt = get_persona_prompt(agent_a_config.search_request.persona)

    if len(persona_prompt) == 0:
        persona_specification = ASSISTANT_SYSTEM_PROMPT_DEFAULT
    else:
        persona_specification = ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
            persona_prompt=persona_prompt
        )

    logger.debug(f"--------{now_start}--------LLM HANDLING START---")

    model = agent_a_config.fast_llm

    msg = [
        HumanMessage(
            content=DIRECT_LLM_PROMPT.format(
                persona_specification=persona_specification, question=question
            )
        )
    ]

    streamed_tokens: list[str | list[str | dict[str, Any]]] = [""]

    for message in model.stream(msg):
        # TODO: in principle, the answer here COULD contain images, but we don't support that yet
        content = message.content
        if not isinstance(content, str):
            raise ValueError(
                f"Expected content to be a string, but got {type(content)}"
            )
        dispatch_custom_event(
            "initial_agent_answer",
            AgentAnswerPiece(
                answer_piece=content,
                level=0,
                level_question_nr=0,
                answer_type="agent_level_answer",
            ),
        )
        streamed_tokens.append(content)

    response = merge_content(*streamed_tokens)
    answer = cast(str, response)

    now_end = datetime.now()

    logger.debug(f"--------{now_end}--{now_end - now_start}--------LLM HANDLING END---")

    return InitialAnswerUpdate(
        initial_answer=answer,
        initial_agent_stats=None,
        generated_sub_questions=[],
        agent_base_end_time=now_end,
        agent_base_metrics=None,
        log_messages=[
            f"{now_end} -- Main - LLM handling: {answer},  Time taken: {now_end - now_start}"
        ],
    )
