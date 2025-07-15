from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.constants import MAX_DR_ITERATION_DEPTH
from onyx.agents.agent_search.dr.models import OrchestrationPlan
from onyx.agents.agent_search.dr.models import OrchestratorDecisonsNoPlan
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.utils import (
    get_answers_history_from_iteration_responses,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import TimeBudget
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.prompts.dr_prompts import FAST_PLAN_GENERATION_PROMPT
from onyx.prompts.dr_prompts import PLAN_GENERATION_PROMPT
from onyx.prompts.dr_prompts import SEQUENTIAL_ITERATIVE_DR_SINGLE_PLAN_DECISION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def orchestrator(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> OrchestrationUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.prompt_builder.raw_user_query
    time_budget = graph_config.behavior.time_budget

    answer_history = get_answers_history_from_iteration_responses(
        state.iteration_responses
    )
    answer_history_string = (
        str(answer_history) if answer_history else "(No answer history yet available)"
    )

    # TODO: do not hardcode this
    time_budget = TimeBudget.DEEP

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    iteration_nr = state.iteration_nr
    plan_information = None

    if iteration_nr >= MAX_DR_ITERATION_DEPTH - 1:
        query_path = DRPath.CLOSER
        query_list = []

    elif time_budget == TimeBudget.FAST:
        if iteration_nr == 0:
            decision_prompt = (
                FAST_PLAN_GENERATION_PROMPT.replace(
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

    else:
        if iteration_nr == 0:
            plan_generation_prompt = (
                PLAN_GENERATION_PROMPT.replace(
                    "---possible_entities---", all_entity_types
                )
                .replace("---possible_relationships---", all_relationship_types)
                .replace("---question---", question)
            )

            try:
                plan_information = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=plan_generation_prompt,
                    schema=OrchestrationPlan,
                    timeout_override=25,
                    max_tokens=1500,
                )
            except Exception as e:
                logger.error(f"Error in plan generation: {e}")
                raise

            write_custom_event(
                "basic_response",
                AgentAnswerPiece(
                    answer_piece=f"\n\nHIGH_LEVEL PLAN: {plan_information.plan}\n\n\n",
                    level=0,
                    level_question_num=0,
                    answer_type="agent_level_answer",
                ),
                writer,
            )
        else:
            plan_information = state.plan_of_record[-1]

        decision_prompt = (
            SEQUENTIAL_ITERATIVE_DR_SINGLE_PLAN_DECISION_PROMPT.replace(
                "---possible_entities---", all_entity_types
            )
            .replace("---possible_relationships---", all_relationship_types)
            .replace("---answer_history_string---", answer_history_string)
            .replace("---question---", question)
            .replace("---iteration_nr---", str(iteration_nr + 1))
            .replace("---current_plan_of_record_string---", plan_information.plan)
        )

        try:
            orchestrator_action = invoke_llm_json(
                llm=graph_config.tooling.primary_llm,
                prompt=decision_prompt,
                schema=OrchestratorDecisonsNoPlan,
                timeout_override=15,
                max_tokens=500,
            )
            next_step = orchestrator_action.next_step
            query_path = next_step.tool
            query_list = next_step.questions
        except Exception as e:
            logger.error(f"Error in approach extraction: {e}")
            raise

    if plan_information:
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
            plan_of_record=[plan_information],
            used_time_budget=0,  # TODO: maybe do remaining instead?
        )
    else:
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
            used_time_budget=0,  # TODO: maybe do remaining instead?
        )
