from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    CS_UPDATE_CONSOLIDATION_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.states import CSUpdateConsolidatorInput
from onyx.agents.agent_search.exploration_2.states import CSUpdateConsolidatorUpdate
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_raw
from onyx.utils.logger import setup_logger

logger = setup_logger()


def cs_update_consolidator(
    state: CSUpdateConsolidatorInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> MainState:
    """
    LangGraph node to close the DR process and finalize the answer.
    """

    datetime.now()
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    old_information, new_information = state.update_pair

    consolidation_content = CS_UPDATE_CONSOLIDATION_PROMPT_TEMPLATE.replace(
        "---original_information---", old_information
    ).replace("---new_information---", new_information)

    consolidation_human_prompt = HumanMessage(content=consolidation_content)
    consolidation_prompt = [consolidation_human_prompt]

    consolidation_response = invoke_llm_raw(
        llm=graph_config.tooling.primary_llm,
        prompt=consolidation_prompt,
    )

    return MainState(
        consolidated_updates=[
            CSUpdateConsolidatorUpdate(
                area=state.area,
                update_type=state.update_type,
                consolidated_update=str(consolidation_response.content),
            )
        ]
    )
