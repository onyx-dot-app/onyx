from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.constants import MAX_DR_ITERATION_DEPTH
from onyx.agents.agent_search.dr.models import OrchestrationFeedbackRequest
from onyx.agents.agent_search.dr.models import OrchestrationPlan
from onyx.agents.agent_search.dr.models import OrchestratorDecisonsNoPlan
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.utils import (
    get_answers_history_from_iteration_responses,
)
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.models import TimeBudget
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.configs.constants import MessageType
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.prompts.dr_prompts import FAST_PLAN_GENERATION_PROMPT
from onyx.prompts.dr_prompts import GET_FEEDBACK_PROMPT
from onyx.prompts.dr_prompts import PLAN_GENERATION_PROMPT
from onyx.prompts.dr_prompts import PLAN_REVISION_PROMPT
from onyx.prompts.dr_prompts import SEQUENTIAL_ITERATIVE_DR_SINGLE_PLAN_DECISION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()

CLARIFICATION_REQUEST_PREFIX = "PLEASE CLARIFY:"
HIGH_LEVEL_PLAN_PREFIX = "HIGH_LEVEL PLAN:"

AVERAGE_TOOL_COSTS = {
    "SEARCH": 1.0,
    "KNOWLEDGE_GRAPH": 2.0,
    "CLOSER": 0.0,
    "USER_FEEDBACK": 0.0,
}

AVERAGE_TOOL_COST_STRING = "\n".join(
    [f"{tool}: {cost}" for tool, cost in AVERAGE_TOOL_COSTS.items()]
)


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

    graph_config.behavior.use_agentic_search = False

    answer_history_string = (
        get_answers_history_from_iteration_responses(state.iteration_responses)
        or "(No answer history yet available)"
    )

    feedback_request = None
    ask_for_feedback_next = False
    feedback_request_needed = False

    remaining_time_budget = state.remaining_time_budget

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    iteration_nr = state.iteration_nr
    plan_information = None

    if iteration_nr >= MAX_DR_ITERATION_DEPTH - 1:
        query_path = DRPath.CLOSER
        query_list = []

    elif time_budget == TimeBudget.FAST:
        if iteration_nr == 0:
            remaining_time_budget = 2.0  # TODO: reorg

            decision_prompt = (
                FAST_PLAN_GENERATION_PROMPT.replace(
                    "---possible_entities---", all_entity_types
                )
                .replace("---possible_relationships---", all_relationship_types)
                .replace("---question---", question)
                .replace("---chat_history_string---", chat_history_string)
                .replace("---average_tool_costs---", AVERAGE_TOOL_COST_STRING)
                .replace("---remaining_time_budget---", str(remaining_time_budget))
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

                query_path = DRPath(response_text)
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

            # by default, we start a new iteration, but if there is a feedback request,
            # we start a new iteration 0 again (set a bit later)

            remaining_time_budget = 4.0  # TODO: reorg
            new_iteration_nr = 1
            ask_for_feedback_next = False
            user_feedback = None
            original_high_level_plan = None
            feedback_request = None
            feedback_request_needed = False

            previous_messages = config["metadata"][
                "config"
            ].inputs.prompt_builder.message_history
            previous_raw_messages = config["metadata"][
                "config"
            ].inputs.prompt_builder.raw_message_history

            # check if there is a feedback request in the most recent message history
            if len(previous_raw_messages) >= 2:

                last_message = previous_raw_messages[-1]
                potential_user_feedback_message = (
                    graph_config.inputs.prompt_builder.raw_user_query
                )

                if (
                    last_message.message_type == MessageType.ASSISTANT
                    and CLARIFICATION_REQUEST_PREFIX in last_message.message
                ):

                    original_high_level_plan = last_message.message.split(
                        CLARIFICATION_REQUEST_PREFIX
                    )[0].strip()
                    if HIGH_LEVEL_PLAN_PREFIX in original_high_level_plan:
                        original_high_level_plan = original_high_level_plan.split(
                            HIGH_LEVEL_PLAN_PREFIX
                        )[1].strip()

                    feedback_request_needed = True
                    user_feedback = potential_user_feedback_message

                    plan_information = state.plan_of_record

                    # overwrite the overall question, as it has not changed if the last message is
                    # a user feedback message
                    # ignore here the last two messages and look for the last human message before that
                    for previous_message in reversed(previous_messages):
                        if (
                            isinstance(previous_message, HumanMessage)
                            and previous_message.content
                            and isinstance(previous_message.content, str)
                        ):
                            graph_config.inputs.prompt_builder.raw_user_query = (
                                previous_message.content
                            )
                            question = graph_config.inputs.prompt_builder.raw_user_query
                            break
                else:
                    user_feedback = None

            if not state.plan_of_record:
                # if no plan is available, generate one

                if user_feedback:

                    # remove clarification request and actual question from the chat history
                    chat_history_string = (
                        get_chat_history_string(
                            graph_config.inputs.prompt_builder.message_history[:-2],
                            MAX_CHAT_HISTORY_MESSAGES,
                        )
                        or "(No chat history yet available)"
                    )

                    plan_generation_prompt = (
                        PLAN_REVISION_PROMPT.replace(
                            "---possible_entities---", all_entity_types
                        )
                        .replace("---possible_relationships---", all_relationship_types)
                        .replace("---question---", question)
                        .replace("---chat_history_string---", chat_history_string)
                        .replace(
                            "---initial_plan---",
                            original_high_level_plan or "(No initial plan available)",
                        )
                        .replace("---user_feedback---", user_feedback)
                    )
                else:
                    plan_generation_prompt = (
                        PLAN_GENERATION_PROMPT.replace(
                            "---possible_entities---", all_entity_types
                        )
                        .replace("---possible_relationships---", all_relationship_types)
                        .replace("---question---", question)
                        .replace("---chat_history_string---", chat_history_string)
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
                        answer_piece=f"HIGH_LEVEL PLAN: {plan_information.plan}\n\n",
                        level=0,
                        level_question_num=0,
                        answer_type="agent_level_answer",
                    ),
                    writer,
                )

                if not user_feedback:
                    get_feedback_prompt = GET_FEEDBACK_PROMPT.replace(
                        "---question---", question
                    ).replace("---high_level_plan---", plan_information.plan)

                    try:
                        feedback_request = invoke_llm_json(
                            llm=graph_config.tooling.primary_llm,
                            prompt=get_feedback_prompt,
                            schema=OrchestrationFeedbackRequest,
                            timeout_override=25,
                            max_tokens=1500,
                        )

                        if feedback_request.feedback_needed:
                            new_iteration_nr = 0
                            ask_for_feedback_next = True
                            query_path = DRPath.USER_FEEDBACK
                            query_list = [feedback_request.feedback_request or ""]

                            write_custom_event(
                                "basic_response",
                                AgentAnswerPiece(
                                    answer_piece=f"PLEASE CLARIFY: {feedback_request.feedback_request}\n\n",
                                    level=0,
                                    level_question_num=0,
                                    answer_type="agent_level_answer",
                                ),
                                writer,
                            )

                    except Exception as e:
                        logger.error(f"Error in feedback request: {e}")
                        raise
                else:
                    new_iteration_nr = 1
                    ask_for_feedback_next = False
            else:
                plan_information = state.plan_of_record

        else:
            # won't be None for DEEP TimeBudget
            plan_information = cast(OrchestrationPlan, state.plan_of_record)
            new_iteration_nr = iteration_nr + 1

        if not ask_for_feedback_next and remaining_time_budget > 0:
            decision_prompt = (
                SEQUENTIAL_ITERATIVE_DR_SINGLE_PLAN_DECISION_PROMPT.replace(
                    "---possible_entities---", all_entity_types
                )
                .replace("---possible_relationships---", all_relationship_types)
                .replace("---answer_history_string---", answer_history_string)
                .replace("---question---", question)
                .replace("---iteration_nr---", str(iteration_nr + 1))
                .replace("---current_plan_of_record_string---", plan_information.plan)
                .replace("---chat_history_string---", chat_history_string)
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
        elif remaining_time_budget <= 0:
            query_path = DRPath.CLOSER
            query_list = ["Answer the question with the information you have."]

    remaining_time_budget = remaining_time_budget - AVERAGE_TOOL_COSTS[query_path]

    return OrchestrationUpdate(
        query_path=[query_path],
        query_list=query_list,
        iteration_nr=new_iteration_nr,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="orchestrator",
                node_start_time=node_start_time,
            )
        ],
        feedback_needed=feedback_request_needed,
        feedback_request=feedback_request,
        plan_of_record=plan_information,
        remaining_time_budget=remaining_time_budget,
    )
