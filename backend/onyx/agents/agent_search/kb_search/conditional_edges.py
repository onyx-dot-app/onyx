from collections.abc import Hashable
from datetime import datetime
from enum import Enum

from langgraph.types import Send

from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import KGSearchType
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.kb_search.states import ResearchObjectInput


class KGAnalysisPath(str, Enum):
    PROCESS_KG_ONLY_ANSWERS = "process_kg_only_answers"
    CONSTRUCT_DEEP_SEARCH_FILTERS = "construct_deep_search_filters"


def simple_vs_search(
    state: MainState,
) -> str:

    identified_strategy = state.updated_strategy or state.strategy

    if (
        identified_strategy == KGAnswerStrategy.DEEP
        or state.search_type == KGSearchType.SEARCH
    ):
        return KGAnalysisPath.CONSTRUCT_DEEP_SEARCH_FILTERS.value
    else:
        return KGAnalysisPath.PROCESS_KG_ONLY_ANSWERS.value


def research_individual_object(
    state: MainState,
) -> list[Send | Hashable] | str:
    edge_start_time = datetime.now()

    assert state.div_con_entities is not None
    assert state.broken_down_question is not None
    assert state.vespa_filter_results is not None

    if (
        state.search_type == KGSearchType.SQL
        and state.strategy == KGAnswerStrategy.DEEP
    ):

        return [
            Send(
                "process_individual_deep_search",
                ResearchObjectInput(
                    research_nr=research_nr + 1,
                    entity=entity,
                    broken_down_question=state.broken_down_question,
                    vespa_filter_results=state.vespa_filter_results,
                    source_division=state.source_division,
                    source_entity_filters=state.source_filters,
                    log_messages=[
                        f"{edge_start_time} -- Main Edge - Parallelize Initial Sub-question Answering"
                    ],
                    step_results=[],
                ),
            )
            for research_nr, entity in enumerate(state.div_con_entities)
        ]
    elif state.search_type == KGSearchType.SEARCH:
        return "filtered_search"
    else:
        raise ValueError(
            f"Invalid combination of search type: {state.search_type} and strategy: {state.strategy}"
        )
