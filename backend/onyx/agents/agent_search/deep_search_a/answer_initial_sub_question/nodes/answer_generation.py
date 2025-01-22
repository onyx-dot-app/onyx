import datetime
from typing import Any
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import merge_message_runs
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionState,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    QAGenerationUpdate,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_sub_question_answer_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_DEFAULT,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_PERSONA,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import UNKNOWN_ANSWER
from onyx.agents.agent_search.shared_graph_utils.utils import get_persona_prompt
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.utils.logger import setup_logger

logger = setup_logger()


def answer_generation(
    state: AnswerQuestionState, config: RunnableConfig
) -> QAGenerationUpdate:
    now_start = datetime.datetime.now()
    logger.debug(f"--------{now_start}--------START ANSWER GENERATION---")

    agent_search_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = state.question
    docs = state.documents
    level, question_nr = parse_question_id(state.question_id)
    persona_prompt = get_persona_prompt(agent_search_config.search_request.persona)

    if len(docs) == 0:
        answer_str = UNKNOWN_ANSWER
        dispatch_custom_event(
            "sub_answers",
            AgentAnswerPiece(
                answer_piece=answer_str,
                level=level,
                level_question_nr=question_nr,
                answer_type="agent_sub_answer",
            ),
        )
    else:
        if len(persona_prompt) > 0:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_DEFAULT
        else:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
                persona_prompt=persona_prompt
            )

        logger.debug(f"Number of verified retrieval docs: {len(docs)}")

        fast_llm = agent_search_config.fast_llm
        msg = build_sub_question_answer_prompt(
            question=question,
            original_question=agent_search_config.search_request.query,
            docs=docs,
            persona_specification=persona_specification,
            config=fast_llm.config,
        )

        response: list[str | list[str | dict[str, Any]]] = []
        for message in fast_llm.stream(
            prompt=msg,
        ):
            # TODO: in principle, the answer here COULD contain images, but we don't support that yet
            content = message.content
            if not isinstance(content, str):
                raise ValueError(
                    f"Expected content to be a string, but got {type(content)}"
                )
            dispatch_custom_event(
                "sub_answers",
                AgentAnswerPiece(
                    answer_piece=content,
                    level=level,
                    level_question_nr=question_nr,
                    answer_type="agent_sub_answer",
                ),
            )
            response.append(content)

        answer_str = merge_message_runs(response, chunk_separator="")[0].content

    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type="sub_answer",
        level=level,
        level_question_nr=question_nr,
    )
    dispatch_custom_event("stream_finished", stop_event)

    return QAGenerationUpdate(
        answer=answer_str,
    )
