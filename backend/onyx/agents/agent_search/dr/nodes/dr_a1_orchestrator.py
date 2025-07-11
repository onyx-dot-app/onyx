from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.dr.constants import MAX_DR_ITERATION_DEPTH
from onyx.agents.agent_search.dr.models import OrchestratorDecisons
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.states import OrchestratorStep
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import TimeBudget
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.prompts.dr_prompts import FAST_DR_DECISION_PROMPT
from onyx.prompts.dr_prompts import ITERATIVE_DR_DECISION_PROMPT
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
    time_budget = graph_config.behavior.time_budget
    current_plan_of_record_string = (
        str(state.plan_of_record[-1])
        if state.plan_of_record
        else "(No plan yet available)"
    )

    answer_history = state.iteration_answers
    answer_history_string = (
        str(answer_history) if answer_history else "(No answer history yet available)"
    )

    # TODO: do not hardcode this
    time_budget = TimeBudget.DEEP

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    iteration_nr = state.iteration_nr

    if iteration_nr >= MAX_DR_ITERATION_DEPTH - 1:
        query_path = DRPath.CLOSER
        query_list = []
        plan_of_record = state.plan_of_record[: state.iteration_nr] + [
            OrchestratorStep(tool=DRPath.CLOSER, questions=[])
        ]

    elif time_budget == TimeBudget.FAST:
        if iteration_nr == 0:
            decision_prompt = (
                FAST_DR_DECISION_PROMPT.replace(
                    "---possible_entities---", all_entity_types
                )
                .replace("---possible_relationships---", all_relationship_types)
                .replace("---question---", question)
            )

            msg = [
                HumanMessage(
                    content=decision_prompt,
                )
            ]
            primary_llm = graph_config.tooling.primary_llm
            response_text = None
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

                query_path = DRPath(response_text.lower())
            except ValueError:
                logger.warning(
                    f"Could not parse LLM response: '{response_text}'. Defaulting to SEARCH."
                )
                query_path = DRPath.SEARCH
            except Exception as e:
                logger.error(f"Error in orchestration: {e}")
                raise e
        else:
            query_path = DRPath.CLOSER

        query_list = [question] if query_path != DRPath.CLOSER else []
        plan_of_record = state.plan_of_record[: state.iteration_nr] + [
            OrchestratorStep(tool=query_path, questions=query_list)
        ]

    else:
        decision_prompt = (
            ITERATIVE_DR_DECISION_PROMPT.replace(
                "---possible_entities---", all_entity_types
            )
            .replace("---possible_relationships---", all_relationship_types)
            .replace("---question---", question)
            .replace("---iteration_nr---", str(iteration_nr))
            .replace(
                "---current_plan_of_record_string---", current_plan_of_record_string
            )
            .replace("---answer_history_string---", answer_history_string)
        )

        msg = [
            HumanMessage(
                content=decision_prompt,
            )
        ]
        primary_llm = graph_config.tooling.primary_llm
        llm_response = run_with_timeout(
            25, primary_llm.invoke, prompt=msg, timeout_override=5, max_tokens=500
        )

        cleaned_response = (
            str(llm_response.content)
            .replace("```json\n", "")
            .replace("\n```", "")
            .replace("\n", "")
        )

        first_bracket = cleaned_response.find("{")
        last_bracket = cleaned_response.rfind("}")
        cleaned_response = cleaned_response[first_bracket : last_bracket + 1]

        try:
            orchestrator_action = OrchestratorDecisons.model_validate_json(
                cleaned_response
            )
            next_step = orchestrator_action.next_step
            plan_of_record = orchestrator_action.plan_of_record
            query_path = next_step.tool
            query_list = next_step.questions
        except Exception as e:
            logger.error(f"Error in approach extraction: {e}")
            raise e

    return OrchestrationUpdate(
        query_path=[query_path],
        query_list=query_list,
        iteration_nr=iteration_nr + 1,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="orchestrator",
                node_start_time=node_start_time,
            )
        ],
        plan_of_record=[plan_of_record],
        used_time_budget=0,  # TODO: maybe do remaining instead?
    )
