from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.constants import AVERAGE_TOOL_COSTS
from onyx.agents.agent_search.dr.constants import DR_TIME_BUDGET_BY_TYPE
from onyx.agents.agent_search.dr.constants import HIGH_LEVEL_PLAN_PREFIX
from onyx.agents.agent_search.dr.dr_prompt_builder import get_dr_prompt_template
from onyx.agents.agent_search.dr.models import DRPromptPurpose
from onyx.agents.agent_search.dr.models import DRTimeBudget
from onyx.agents.agent_search.dr.models import OrchestrationPlan
from onyx.agents.agent_search.dr.models import OrchestratorDecisonsNoPlan
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.utils import (
    get_answers_history_from_iteration_responses,
)
from onyx.agents.agent_search.dr.utils import get_prompt_question
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.utils.logger import setup_logger

logger = setup_logger()


def orchestrator(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> OrchestrationUpdate:
    """
    LangGraph node to decide the next step in the DR process.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.original_question
    if not question:
        raise ValueError("Question is required for orchestrator")

    plan_of_record = state.plan_of_record
    clarification = state.clarification
    iteration_nr = state.iteration_nr + 1
    time_budget = graph_config.behavior.time_budget
    remaining_time_budget = state.remaining_time_budget
    chat_history_string = state.chat_history_string or "(No chat history yet available)"
    answer_history_string = (
        get_answers_history_from_iteration_responses(state.iteration_responses)
        or "(No answer history yet available)"
    )
    prompt_question = get_prompt_question(question, clarification)

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    # default to closer
    query_path = DRPath.CLOSER
    query_list = ["Answer the question with the information you have."]
    decision_prompt = None

    if time_budget == DRTimeBudget.FAST:
        if iteration_nr == 1:
            remaining_time_budget = DR_TIME_BUDGET_BY_TYPE[DRTimeBudget.FAST]

        base_decision_prompt = get_dr_prompt_template(
            DRPromptPurpose.NEXT_STEP,
            DRTimeBudget.FAST,
            entity_types_string=all_entity_types,
            relationship_types_string=all_relationship_types,
            available_tools=state.available_tools,
        )
        decision_prompt = (
            base_decision_prompt.replace("---question---", question)
            .replace("---chat_history_string---", chat_history_string)
            .replace("---answer_history_string---", answer_history_string)
            .replace("---iteration_nr---", str(iteration_nr))
            .replace("---remaining_time_budget---", str(remaining_time_budget))
        )

    else:
        if iteration_nr == 1 and not plan_of_record:
            # by default, we start a new iteration, but if there is a feedback request,
            # we start a new iteration 0 again (set a bit later)

            remaining_time_budget = DR_TIME_BUDGET_BY_TYPE[DRTimeBudget.DEEP]

            base_plan_prompt = get_dr_prompt_template(
                DRPromptPurpose.PLAN,
                DRTimeBudget.DEEP,
                entity_types_string=all_entity_types,
                relationship_types_string=all_relationship_types,
                available_tools=state.available_tools,
            )
            plan_generation_prompt = base_plan_prompt.replace(
                "---question---", prompt_question
            ).replace("---chat_history_string---", chat_history_string)

            try:
                plan_of_record = invoke_llm_json(
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
                    answer_piece=f"{HIGH_LEVEL_PLAN_PREFIX} {plan_of_record.plan}\n\n",
                    level=0,
                    level_question_num=0,
                    answer_type="agent_level_answer",
                ),
                writer,
            )

        if not plan_of_record:
            raise ValueError(
                "Plan information is required for iterative decision making"
            )

        base_decision_prompt = get_dr_prompt_template(
            DRPromptPurpose.NEXT_STEP,
            DRTimeBudget.DEEP,
            entity_types_string=all_entity_types,
            relationship_types_string=all_relationship_types,
            available_tools=state.available_tools,
        )
        decision_prompt = (
            base_decision_prompt.replace(
                "---answer_history_string---", answer_history_string
            )
            .replace("---question---", prompt_question)
            .replace("---iteration_nr---", str(iteration_nr))
            .replace("---current_plan_of_record_string---", plan_of_record.plan)
            .replace("---chat_history_string---", chat_history_string)
            .replace("---remaining_time_budget---", str(remaining_time_budget))
        )

    if remaining_time_budget > 0:
        if decision_prompt is None:
            raise ValueError("Decision prompt is required")
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
            query_list = [q for q in (next_step.questions or []) if q is not None]
        except Exception as e:
            logger.error(f"Error in approach extraction: {e}")
            raise e

        if query_path in AVERAGE_TOOL_COSTS:
            remaining_time_budget = (
                remaining_time_budget - AVERAGE_TOOL_COSTS[query_path]
            )
        else:
            remaining_time_budget = (
                remaining_time_budget - 1.5
            )  # estimate for custom tools. TODO: fix!

    return OrchestrationUpdate(
        query_path=[query_path],
        query_list=query_list or [],
        iteration_nr=iteration_nr,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="orchestrator",
                node_start_time=node_start_time,
            )
        ],
        clarification=clarification,
        plan_of_record=plan_of_record,
        remaining_time_budget=remaining_time_budget,
    )
