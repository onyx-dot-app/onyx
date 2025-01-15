import datetime

from langchain_core.callbacks.manager import dispatch_custom_event

from onyx.agent_search.pro_search_b.answer_initial_sub_question.states import (
    AnswerQuestionState,
)
from onyx.agent_search.pro_search_b.answer_initial_sub_question.states import (
    QAGenerationUpdate,
)
from onyx.agent_search.shared_graph_utils.utils import get_persona_prompt
from onyx.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.chat.models import AgentAnswerPiece
from onyx.utils.logger import setup_logger

logger = setup_logger()


def answer_generation(state: AnswerQuestionState) -> QAGenerationUpdate:
    now_start = datetime.datetime.now()
    logger.debug(f"--------{now_start}--------START ANSWER GENERATION---")

    state["question"]
    state["documents"]
    level, question_nr = parse_question_id(state["question_id"])
    get_persona_prompt(state["subgraph_config"].search_request.persona)

    dispatch_custom_event(
        "sub_answers",
        AgentAnswerPiece(
            answer_piece="",
            level=level,
            level_question_nr=question_nr,
            answer_type="agent_sub_answer",
        ),
    )
    answer_str = ""

    return QAGenerationUpdate(
        answer=answer_str,
    )
