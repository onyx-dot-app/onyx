from collections.abc import Hashable
from typing import cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Send

from onyx.agents.agent_search.dc_search_analysis.states import ObjectInformationInput
from onyx.agents.agent_search.dc_search_analysis.states import (
    ObjectResearchInformationUpdate,
)
from onyx.agents.agent_search.dc_search_analysis.states import ObjectSourceInput
from onyx.agents.agent_search.dc_search_analysis.states import (
    SearchSourcesObjectsUpdate,
)
from onyx.agents.agent_search.models import GraphConfig


def parallel_object_source_research_edge(
    state: SearchSourcesObjectsUpdate, config: RunnableConfig
) -> list[Send | Hashable]:
    """
    LangGraph edge to parallelize the research for an individual object and source
    """

    search_objects = state.analysis_objects
    search_sources = state.analysis_sources

    object_source_combinations = [
        (object, source) for object in search_objects for source in search_sources
    ]

    return [
        Send(
            "research_object_source",
            ObjectSourceInput(
                object_source_combination=object_source_combination,
                log_messages=[],
            ),
        )
        for object_source_combination in object_source_combinations
    ]


def parallel_object_research_consolidation_edge(
    state: ObjectResearchInformationUpdate, config: RunnableConfig
) -> list[Send | Hashable]:
    """
    LangGraph edge to parallelize the research for an individual object and source
    """
    cast(GraphConfig, config["metadata"]["config"])
    object_research_information_results = state.object_research_information_results

    return [
        Send(
            "consolidate_object_research",
            ObjectInformationInput(
                object_information=object_information,
                log_messages=[],
            ),
        )
        for object_information in object_research_information_results
    ]
