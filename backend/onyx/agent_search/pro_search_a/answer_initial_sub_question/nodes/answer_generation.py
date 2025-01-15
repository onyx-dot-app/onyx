import datetime
from typing import Any

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import merge_message_runs

from onyx.agent_search.pro_search_a.answer_initial_sub_question.states import (
    AnswerQuestionState,
)
from onyx.agent_search.pro_search_a.answer_initial_sub_question.states import (
    QAGenerationUpdate,
)
from onyx.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_sub_question_answer_prompt,
)
from onyx.agent_search.shared_graph_utils.prompts import ASSISTANT_SYSTEM_PROMPT_DEFAULT
from onyx.agent_search.shared_graph_utils.prompts import ASSISTANT_SYSTEM_PROMPT_PERSONA
from onyx.agent_search.shared_graph_utils.utils import get_persona_prompt
from onyx.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.chat.models import AgentAnswerPiece, StreamStopInfo, StreamStopReason
from onyx.utils.logger import setup_logger

logger = setup_logger()


def answer_generation(state: AnswerQuestionState) -> QAGenerationUpdate:
    now_start = datetime.datetime.now()
    logger.debug(f"--------{now_start}--------START ANSWER GENERATION---")

    question = state["question"]
    docs = state["documents"]
    level, question_nr = parse_question_id(state["question_id"])
    persona_prompt = get_persona_prompt(state["subgraph_config"].search_request.persona)

    if len(docs) == 0:
        dispatch_custom_event(
            "sub_answers",
            AgentAnswerPiece(
                answer_piece="I don't know",
                level=level,
                level_question_nr=question_nr,
                answer_type="agent_sub_answer",
            ),
        )
        answer_str = "I don't know"
    else:
        if len(persona_prompt) > 0:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_DEFAULT
        else:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
                persona_prompt=persona_prompt
            )

        logger.debug(f"Number of verified retrieval docs: {len(docs)}")

        msg = build_sub_question_answer_prompt(
            question=question,
            original_question=state["subgraph_config"].search_request.query,
            docs=docs,
            persona_specification=persona_specification,
        )

        fast_llm = state["subgraph_fast_llm"]
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

    stop_event = StreamStopInfo(stop_reason=StreamStopReason.FINISHED, level=level, level_question_nr=question_nr)
    dispatch_custom_event("sub_answer_finished", stop_event)

    return QAGenerationUpdate(
        answer=answer_str,
    )
