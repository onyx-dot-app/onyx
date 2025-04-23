from collections.abc import Hashable
from datetime import datetime
from typing import Literal

from langgraph.types import Send
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import ResearchObjectInput
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece


def simple_vs_search(
    state: MainState,
) -> Literal["process_kg_only_answers", "construct_deep_search_filters"]:
    if state.strategy == KGAnswerStrategy.DEEP:
        return "construct_deep_search_filters"
    else:
        return "process_kg_only_answers"


def research_individual_object(
    state: MainState,
    writer: StreamWriter,
    # ) -> list[Send | Hashable] | Literal["individual_deep_search"]:
) -> list[Send | Hashable]:
    edge_start_time = datetime.now()

    # if (
    #     not state.div_con_entities
    #     or not state.broken_down_question
    #     or not state.vespa_filter_results
    # ):
    #     return "individual_deep_search"

    # else:

    assert state.div_con_entities is not None
    assert state.broken_down_question is not None
    assert state.vespa_filter_results is not None

    write_custom_event(
        "initial_agent_answer",
        AgentAnswerPiece(
            answer_piece=f"Researching {len(state.div_con_entities)} topics...  -  ",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )

    return [
        Send(
            "process_individual_deep_search",
            ResearchObjectInput(
                entity=entity,
                broken_down_question=state.broken_down_question,
                vespa_filter_results=state.vespa_filter_results,
                source_division=state.source_division,
                source_entity_filters=state.source_filters,
                log_messages=[
                    f"{edge_start_time} -- Main Edge - Parallelize Initial Sub-question Answering"
                ],
            ),
        )
        for entity in state.div_con_entities
    ]
