from collections.abc import Hashable
from datetime import datetime
from typing import Literal

from langgraph.types import Send

from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import ResearchObjectInput


def simple_vs_search(
    state: MainState,
) -> Literal["process_kg_only_answers", "construct_deep_search_filters"]:
    if state.strategy == KGAnswerStrategy.SIMPLE or len(state.relationships) > 0:
        return "construct_deep_search_filters"
    else:
        return "process_kg_only_answers"


def research_individual_object(
    state: MainState,
) -> list[Send | Hashable] | Literal["individual_deep_search"]:
    edge_start_time = datetime.now()

    if (
        not state.div_con_entities
        or not state.broken_down_question
        or not state.vespa_filter_results
    ):
        return "individual_deep_search"

    else:
        return [
            Send(
                "process_individual_deep_search",
                ResearchObjectInput(
                    entity=entity,
                    broken_down_question=state.broken_down_question,
                    vespa_filter_results=state.vespa_filter_results,
                    log_messages=[
                        f"{edge_start_time} -- Main Edge - Parallelize Initial Sub-question Answering"
                    ],
                ),
            )
            for entity in state.div_con_entities
        ]
