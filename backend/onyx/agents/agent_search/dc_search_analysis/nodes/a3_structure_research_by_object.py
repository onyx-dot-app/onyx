from collections import defaultdict
from typing import Dict
from typing import List

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dc_search_analysis.states import MainState
from onyx.agents.agent_search.dc_search_analysis.states import (
    ObjectResearchInformationUpdate,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def structure_research_by_object(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ObjectResearchInformationUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    object_source_research_results = state.object_source_research_results

    object_research_information_results: List[Dict[str, str]] = []
    object_research_information_results_list: Dict[str, List[str]] = defaultdict(list)

    for object_source_research in object_source_research_results:
        object = object_source_research["object"]
        source = object_source_research["source"]
        research_result = object_source_research["research_result"]

        object_research_information_results_list[object].append(
            f"Source: {source}\n{research_result}"
        )

    for object, information in object_research_information_results_list.items():
        object_research_information_results.append(
            {"object": object, "information": "\n".join(information)}
        )

    logger.debug("DivCon Step A3 - Object Research Information Structuring - completed")

    return ObjectResearchInformationUpdate(
        object_research_information_results=object_research_information_results,
        log_messages=["A3 - Object Research Information structured"],
    )
