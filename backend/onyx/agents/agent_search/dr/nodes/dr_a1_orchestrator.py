from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.prompts.dr_prompts import DR_DECISION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def orchestrator(state: MainState, config: RunnableConfig) -> OrchestrationUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.prompt_builder.raw_user_query

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    iteration_nr = state.iteration_nr

    if iteration_nr > 0:
        query_path = DRPath.CLOSER

    else:
        decision_prompt = (
            DR_DECISION_PROMPT.replace("---possible_entities---", all_entity_types)
            .replace("---possible_relationships---", all_relationship_types)
            .replace("---question---", question)
        )

        msg = [
            HumanMessage(
                content=decision_prompt,
            )
        ]
        primary_llm = graph_config.tooling.primary_llm
        # Grader
        try:
            llm_response = run_with_timeout(
                5,
                # fast_llm.invoke,
                primary_llm.invoke,
                prompt=msg,
                timeout_override=5,
                max_tokens=5,
            )

            cleaned_response = (
                str(llm_response.content)
                .replace("```json\n", "")
                .replace("\n```", "")
                .replace("\n", "")
            )
            if "ANSWER:" in cleaned_response:
                response_text = cleaned_response.split("ANSWER:")[1].strip()
            else:
                response_text = cleaned_response.strip()

            # Normalize the response to match enum values
            response_text = response_text.lower()
            if response_text == "search":
                query_path = DRPath.SEARCH
            elif response_text == "knowledge_graph":
                query_path = DRPath.KNOWLEDGE_GRAPH
            else:
                logger.warning(
                    f"Invalid response from LLM: '{response_text}'. Defaulting to SEARCH."
                )
                query_path = DRPath.SEARCH

        except Exception as e:
            logger.error(f"Error in orchestration: {e}")
            raise e

        # End node

    return OrchestrationUpdate(
        query_path=[query_path],
        iteration_nr=iteration_nr + 1,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="orchestrator",
                node_start_time=node_start_time,
            )
        ],
    )
