from collections.abc import Hashable
from datetime import datetime
from typing import Literal

from langgraph.types import Send

from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionInput,
)
from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    AnswerQuestionOutput,
)
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.deep_search_a.main.states import (
    RequireRefinedAnswerUpdate,
)
from onyx.agents.agent_search.shared_graph_utils.utils import make_question_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


def parallelize_initial_sub_question_answering(
    state: MainState,
) -> list[Send | Hashable]:
    now_start = datetime.now()
    if len(state.initial_decomp_questions) > 0:
        # sub_question_record_ids = [subq_record.id for subq_record in state["sub_question_records"]]
        # if len(state["sub_question_records"]) == 0:
        #     if state["config"].use_persistence:
        #         raise ValueError("No sub-questions found for initial decompozed questions")
        #     else:
        #         # in this case, we are doing retrieval on the original question.
        #         # to make all the logic consistent, we create a new sub-question
        #         # with the same content as the original question
        #         sub_question_record_ids = [1] * len(state["initial_decomp_questions"])

        return [
            Send(
                "answer_query_subgraph",
                AnswerQuestionInput(
                    question=question,
                    question_id=make_question_id(0, question_nr + 1),
                    log_messages=[
                        f"{now_start} -- Main Edge - Parallelize Initial Sub-question Answering"
                    ],
                ),
            )
            for question_nr, question in enumerate(state.initial_decomp_questions)
        ]

    else:
        return [
            Send(
                "ingest_answers",
                AnswerQuestionOutput(
                    answer_results=[],
                ),
            )
        ]


# Define the function that determines whether to continue or not
def continue_to_refined_answer_or_end(
    state: RequireRefinedAnswerUpdate,
) -> Literal["refined_sub_question_creation", "logging_node"]:
    if state.require_refined_answer:
        return "refined_sub_question_creation"
    else:
        return "logging_node"


def parallelize_refined_sub_question_answering(
    state: MainState,
) -> list[Send | Hashable]:
    now_start = datetime.now()
    if len(state.refined_sub_questions) > 0:
        return [
            Send(
                "answer_refined_question",
                AnswerQuestionInput(
                    question=question_data.sub_question,
                    question_id=make_question_id(1, question_nr),
                    log_messages=[
                        f"{now_start} -- Main Edge - Parallelize Refined Sub-question Answering"
                    ],
                ),
            )
            for question_nr, question_data in state.refined_sub_questions.items()
        ]

    else:
        return [
            Send(
                "ingest_refined_sub_answers",
                AnswerQuestionOutput(
                    answer_results=[],
                ),
            )
        ]
