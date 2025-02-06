from collections.abc import Hashable
from datetime import datetime

from langgraph.types import Send

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionOutput,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    SubQuestionAnsweringInput,
)
from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.states import (
    SubQuestionRetrievalState,
)
from onyx.agents.agent_search.shared_graph_utils.utils import make_question_id


def parallelize_initial_sub_question_answering(
    state: SubQuestionRetrievalState,
) -> list[Send | Hashable]:
    """
    LangGraph edge to parallelize the initial sub-question answering.
    """
    edge_start_time = datetime.now()
    if len(state.initial_sub_questions) > 0:
        return [
            Send(
                "answer_sub_question_subgraphs",
                SubQuestionAnsweringInput(
                    question=question,
                    question_id=make_question_id(0, question_num + 1),
                    log_messages=[
                        f"{edge_start_time} -- Main Edge - Parallelize Initial Sub-question Answering"
                    ],
                ),
            )
            for question_num, question in enumerate(state.initial_sub_questions)
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
