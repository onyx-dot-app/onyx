from collections.abc import Hashable
from typing import Literal

from langgraph.types import Send

from onyx.agent_search.core_state import extract_core_fields_for_subgraph
from onyx.agent_search.pro_search_b.answer_initial_sub_question.states import (
    AnswerQuestionInput,
)
from onyx.agent_search.pro_search_b.answer_initial_sub_question.states import (
    AnswerQuestionOutput,
)
from onyx.agent_search.pro_search_b.main.states import MainState
from onyx.agent_search.pro_search_b.main.states import RequireRefinedAnswerUpdate
from onyx.agent_search.shared_graph_utils.utils import make_question_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


def parallelize_initial_sub_question_answering(
    state: MainState,
) -> list[Send | Hashable]:
    if len(state["initial_decomp_questions"]) > 0:
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
                    **extract_core_fields_for_subgraph(state),
                    question=question,
                    question_id=make_question_id(0, question_nr),
                ),
            )
            for question_nr, question in enumerate(state["initial_decomp_questions"])
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
) -> Literal["refined_decompose", "logging_node"]:
    if state["require_refined_answer"]:
        return "refined_decompose"
    else:
        return "logging_node"


def parallelize_refined_sub_question_answering(
    state: MainState,
) -> list[Send | Hashable]:
    if len(state["refined_sub_questions"]) > 0:
        return [
            Send(
                "answer_refinement_sub_question",
                AnswerQuestionInput(
                    **extract_core_fields_for_subgraph(state),
                    question=question_data.sub_question,
                    question_id=make_question_id(1, question_nr),
                ),
            )
            for question_nr, question_data in state["refined_sub_questions"].items()
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
