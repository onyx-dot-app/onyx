from datetime import datetime
from typing import cast

from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.constants import DR_TIME_BUDGET_BY_TYPE
from onyx.agents.agent_search.dr.constants import HIGH_LEVEL_PLAN_PREFIX
from onyx.agents.agent_search.dr.dr_prompt_builder import (
    get_dr_prompt_orchestration_templates,
)
from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import DRPromptPurpose
from onyx.agents.agent_search.dr.models import OrchestrationPlan
from onyx.agents.agent_search.dr.models import OrchestratorDecisonsNoPlan
from onyx.agents.agent_search.dr.states import IterationInstructions
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.utils import aggregate_context
from onyx.agents.agent_search.dr.utils import create_tool_call_string
from onyx.agents.agent_search.dr.utils import get_prompt_question
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import run_with_timeout
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.configs.agent_configs import TF_DR_TIMEOUT_LONG
from onyx.configs.agent_configs import TF_DR_TIMEOUT_SHORT
from onyx.kg.utils.extraction_utils import get_entity_types_str
from onyx.kg.utils.extraction_utils import get_relationship_types_str
from onyx.prompts.dr_prompts import DEFAULLT_DECISION_PROMPT
from onyx.prompts.dr_prompts import REPEAT_PROMPT
from onyx.prompts.dr_prompts import SUFFICIENT_INFORMATION_STRING
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DECISION_SYSTEM_PROMPT_PREFIX = "Here are general instructions by the user, which \
may or may not influence the decision what to do next:\n\n"


def _get_implied_next_tool_based_on_tool_call_history(
    tools_used: list[str],
) -> str | None:
    """
    Identify the next tool based on the tool call history. Initially, we only support
    special handling of the image generation tool.
    """
    if tools_used[-1] == DRPath.IMAGE_GENERATION.value:
        return DRPath.LOGGER.value
    else:
        return None


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

    state.original_question

    available_tools = state.available_tools

    plan_of_record = state.plan_of_record
    clarification = state.clarification
    assistant_system_prompt = state.assistant_system_prompt

    if assistant_system_prompt:
        decision_system_prompt: str = (
            DEFAULLT_DECISION_PROMPT
            + _DECISION_SYSTEM_PROMPT_PREFIX
            + assistant_system_prompt
        )
    else:
        decision_system_prompt = DEFAULLT_DECISION_PROMPT

    iteration_nr = state.iteration_nr + 1
    current_step_nr = state.current_step_nr

    research_type = graph_config.behavior.research_type
    remaining_time_budget = state.remaining_time_budget
    chat_history_string = state.chat_history_string or "(No chat history yet available)"
    answer_history_string = (
        aggregate_context(state.iteration_responses, include_documents=True).context
        or "(No answer history yet available)"
    )

    next_tool_name = None

    # Identify early exit condition based on tool call history

    next_tool_based_on_tool_call_history = (
        _get_implied_next_tool_based_on_tool_call_history(state.tools_used)
    )

    if next_tool_based_on_tool_call_history == DRPath.LOGGER.value:
        return OrchestrationUpdate(
            tools_used=[DRPath.LOGGER.value],
            query_list=[],
            iteration_nr=iteration_nr,
            current_step_nr=current_step_nr,
            log_messages=[
                get_langgraph_node_log_string(
                    graph_component="main",
                    node_name="orchestrator",
                    node_start_time=node_start_time,
                )
            ],
            plan_of_record=plan_of_record,
            remaining_time_budget=remaining_time_budget,
            iteration_instructions=[
                IterationInstructions(
                    iteration_nr=iteration_nr,
                    plan=plan_of_record.plan if plan_of_record else None,
                    reasoning="",
                    purpose="",
                )
            ],
        )

    # no early exit forced. Continue.

    available_tools = state.available_tools or {}

    uploaded_context = state.uploaded_test_context or ""
    uploaded_image_context = state.uploaded_image_context or []

    questions = [
        f"{iteration_response.tool}: {iteration_response.question}"
        for iteration_response in state.iteration_responses
        if len(iteration_response.question) > 0
    ]

    question_history_string = (
        "\n".join(f"  - {question}" for question in questions)
        if questions
        else "(No question history yet available)"
    )

    prompt_question = get_prompt_question(question, clarification)

    gaps_str = (
        ("\n  - " + "\n  - ".join(state.gaps))
        if state.gaps
        else "(No explicit gaps were pointed out so far)"
    )

    all_entity_types = get_entity_types_str(active=True)
    all_relationship_types = get_relationship_types_str(active=True)

    # default to closer
    query_list = ["Answer the question with the information you have."]
    decision_prompt = None

    reasoning_result = "(No reasoning result provided yet.)"
    tool_calls_string = "(No tool calls provided yet.)"

    if research_type not in ResearchType:
        raise ValueError(f"Invalid research type: {research_type}")

    if research_type in [ResearchType.THOUGHTFUL, ResearchType.FAST]:
        if iteration_nr == 1:
            remaining_time_budget = DR_TIME_BUDGET_BY_TYPE[research_type]

        elif remaining_time_budget <= 0:

            write_custom_event(
                current_step_nr,
                SectionEnd(),
                writer,
            )

            current_step_nr += 1

            return OrchestrationUpdate(
                tools_used=[DRPath.CLOSER.value],
                current_step_nr=current_step_nr,
                query_list=[],
                iteration_nr=iteration_nr,
                log_messages=[
                    get_langgraph_node_log_string(
                        graph_component="main",
                        node_name="orchestrator",
                        node_start_time=node_start_time,
                    )
                ],
                plan_of_record=plan_of_record,
                remaining_time_budget=remaining_time_budget,
                iteration_instructions=[
                    IterationInstructions(
                        iteration_nr=iteration_nr,
                        plan=None,
                        reasoning="Time to wrap up.",
                        purpose="",
                    )
                ],
            )

        elif iteration_nr > 1 and remaining_time_budget > 0:
            # for each iteration past the first one, we need to see whether we
            # have enough information to answer the question.
            # if we do, we can stop the iteration and return the answer.
            # if we do not, we need to continue the iteration.

            base_reasoning_prompt = get_dr_prompt_orchestration_templates(
                DRPromptPurpose.NEXT_STEP_REASONING,
                ResearchType.THOUGHTFUL,
                entity_types_string=all_entity_types,
                relationship_types_string=all_relationship_types,
                available_tools=available_tools,
            )

            reasoning_prompt = base_reasoning_prompt.build(
                question=question,
                chat_history_string=chat_history_string,
                answer_history_string=answer_history_string,
                iteration_nr=str(iteration_nr),
                remaining_time_budget=str(remaining_time_budget),
                uploaded_context=uploaded_context,
            )

            reasoning_tokens: list[str] = [""]

            reasoning_tokens, _, _ = run_with_timeout(
                TF_DR_TIMEOUT_LONG,
                lambda: stream_llm_answer(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        decision_system_prompt,
                        reasoning_prompt,
                        uploaded_image_context=uploaded_image_context,
                    ),
                    event_name="basic_response",
                    writer=writer,
                    agent_answer_level=0,
                    agent_answer_question_num=0,
                    agent_answer_type="agent_level_answer",
                    timeout_override=TF_DR_TIMEOUT_LONG,
                    answer_piece=StreamingType.REASONING_DELTA.value,
                    ind=current_step_nr,
                    # max_tokens=None,
                ),
            )

            write_custom_event(
                current_step_nr,
                SectionEnd(),
                writer,
            )

            current_step_nr += 1

            reasoning_result = cast(str, merge_content(*reasoning_tokens))

            if SUFFICIENT_INFORMATION_STRING in reasoning_result:
                return OrchestrationUpdate(
                    tools_used=[DRPath.CLOSER.value],
                    current_step_nr=current_step_nr,
                    query_list=[],
                    iteration_nr=iteration_nr,
                    log_messages=[
                        get_langgraph_node_log_string(
                            graph_component="main",
                            node_name="orchestrator",
                            node_start_time=node_start_time,
                        )
                    ],
                    plan_of_record=plan_of_record,
                    remaining_time_budget=remaining_time_budget,
                    iteration_instructions=[
                        IterationInstructions(
                            iteration_nr=iteration_nr,
                            plan=None,
                            reasoning=reasoning_result,
                            purpose="",
                        )
                    ],
                )

        # for Thoughtful mode, we force a tool if requested an available
        available_tools_for_decision = available_tools
        force_use_tool = graph_config.tooling.force_use_tool
        if iteration_nr == 1 and force_use_tool and force_use_tool.force_use:

            forced_tool_name = force_use_tool.tool_name

            available_tool_dict = {
                available_tool.tool_object.name: available_tool
                for _, available_tool in available_tools.items()
                if available_tool.tool_object
            }

            if forced_tool_name in available_tool_dict.keys():
                forced_tool = available_tool_dict[forced_tool_name]

                available_tools_for_decision = {forced_tool.name: forced_tool}

        base_decision_prompt = get_dr_prompt_orchestration_templates(
            DRPromptPurpose.NEXT_STEP,
            ResearchType.THOUGHTFUL,
            entity_types_string=all_entity_types,
            relationship_types_string=all_relationship_types,
            available_tools=available_tools_for_decision,
        )
        decision_prompt = base_decision_prompt.build(
            question=question,
            chat_history_string=chat_history_string,
            answer_history_string=answer_history_string,
            iteration_nr=str(iteration_nr),
            remaining_time_budget=str(remaining_time_budget),
            reasoning_result=reasoning_result,
            uploaded_context=uploaded_context,
        )

        if remaining_time_budget > 0:
            try:
                orchestrator_action = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        decision_system_prompt,
                        decision_prompt,
                        uploaded_image_context=uploaded_image_context,
                    ),
                    schema=OrchestratorDecisonsNoPlan,
                    timeout_override=TF_DR_TIMEOUT_SHORT,
                    # max_tokens=2500,
                )
                next_step = orchestrator_action.next_step
                next_tool_name = next_step.tool
                query_list = [q for q in (next_step.questions or [])]

                tool_calls_string = create_tool_call_string(next_tool_name, query_list)

            except Exception as e:
                logger.error(f"Error in approach extraction: {e}")
                raise e

            if next_tool_name in available_tools.keys():
                remaining_time_budget -= available_tools[next_tool_name].cost
            else:
                logger.warning(f"Tool {next_tool_name} not found in available tools")
                remaining_time_budget -= 1.0

        else:
            reasoning_result = "Time to wrap up."
            next_tool_name = DRPath.CLOSER.value

    elif research_type == ResearchType.DEEP:
        if iteration_nr == 1 and not plan_of_record:
            # by default, we start a new iteration, but if there is a feedback request,
            # we start a new iteration 0 again (set a bit later)

            remaining_time_budget = DR_TIME_BUDGET_BY_TYPE[ResearchType.DEEP]

            base_plan_prompt = get_dr_prompt_orchestration_templates(
                DRPromptPurpose.PLAN,
                ResearchType.DEEP,
                entity_types_string=all_entity_types,
                relationship_types_string=all_relationship_types,
                available_tools=available_tools,
            )
            plan_generation_prompt = base_plan_prompt.build(
                question=prompt_question,
                chat_history_string=chat_history_string,
                uploaded_context=uploaded_context,
            )

            try:
                plan_of_record = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        decision_system_prompt,
                        plan_generation_prompt,
                        uploaded_image_context=uploaded_image_context,
                    ),
                    schema=OrchestrationPlan,
                    timeout_override=TF_DR_TIMEOUT_SHORT,
                    # max_tokens=3000,
                )
            except Exception as e:
                logger.error(f"Error in plan generation: {e}")
                raise

            write_custom_event(
                current_step_nr,
                ReasoningStart(),
                writer,
            )

            start_time = datetime.now()

            repeat_plan_prompt = REPEAT_PROMPT.build(
                original_information=f"{HIGH_LEVEL_PLAN_PREFIX}\n\n {plan_of_record.plan}"
            )

            _, _, _ = run_with_timeout(
                TF_DR_TIMEOUT_LONG,
                lambda: stream_llm_answer(
                    llm=graph_config.tooling.primary_llm,
                    prompt=repeat_plan_prompt,
                    event_name="basic_response",
                    writer=writer,
                    agent_answer_level=0,
                    agent_answer_question_num=0,
                    agent_answer_type="agent_level_answer",
                    timeout_override=TF_DR_TIMEOUT_LONG,
                    answer_piece=StreamingType.REASONING_DELTA.value,
                    ind=current_step_nr,
                ),
            )

            end_time = datetime.now()
            logger.debug(f"Time taken for plan streaming: {end_time - start_time}")

            write_custom_event(
                current_step_nr,
                SectionEnd(),
                writer,
            )
            current_step_nr += 1

        if not plan_of_record:
            raise ValueError(
                "Plan information is required for iterative decision making"
            )

        base_decision_prompt = get_dr_prompt_orchestration_templates(
            DRPromptPurpose.NEXT_STEP,
            ResearchType.DEEP,
            entity_types_string=all_entity_types,
            relationship_types_string=all_relationship_types,
            available_tools=available_tools,
        )
        decision_prompt = base_decision_prompt.build(
            answer_history_string=answer_history_string,
            question_history_string=question_history_string,
            question=prompt_question,
            iteration_nr=str(iteration_nr),
            current_plan_of_record_string=plan_of_record.plan,
            chat_history_string=chat_history_string,
            remaining_time_budget=str(remaining_time_budget),
            gaps=gaps_str,
            uploaded_context=uploaded_context,
        )

        if remaining_time_budget > 0:
            try:
                orchestrator_action = invoke_llm_json(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        decision_system_prompt,
                        decision_prompt,
                        uploaded_image_context=uploaded_image_context,
                    ),
                    schema=OrchestratorDecisonsNoPlan,
                    timeout_override=TF_DR_TIMEOUT_LONG,
                    # max_tokens=1500,
                )
                next_step = orchestrator_action.next_step
                next_tool_name = next_step.tool

                query_list = [q for q in (next_step.questions or [])]
                reasoning_result = orchestrator_action.reasoning

                tool_calls_string = create_tool_call_string(next_tool_name, query_list)
            except Exception as e:
                logger.error(f"Error in approach extraction: {e}")
                raise e

            if next_tool_name in available_tools.keys():
                remaining_time_budget -= available_tools[next_tool_name].cost
            else:
                logger.warning(f"Tool {next_tool_name} not found in available tools")
                remaining_time_budget -= 1.0
        else:
            reasoning_result = "Time to wrap up."
            next_tool_name = DRPath.CLOSER.value

        write_custom_event(
            current_step_nr,
            ReasoningStart(),
            writer,
        )

        repeat_reasoning_prompt = REPEAT_PROMPT.build(
            original_information=reasoning_result
        )

        _, _, _ = run_with_timeout(
            TF_DR_TIMEOUT_LONG,
            lambda: stream_llm_answer(
                llm=graph_config.tooling.primary_llm,
                prompt=repeat_reasoning_prompt,
                event_name="basic_response",
                writer=writer,
                agent_answer_level=0,
                agent_answer_question_num=0,
                agent_answer_type="agent_level_answer",
                timeout_override=TF_DR_TIMEOUT_LONG,
                answer_piece=StreamingType.REASONING_DELTA.value,
                ind=current_step_nr,
                # max_tokens=None,
            ),
        )

        write_custom_event(
            current_step_nr,
            SectionEnd(),
            writer,
        )

        current_step_nr += 1

    else:
        raise NotImplementedError(f"Research type {research_type} is not implemented.")

    base_next_step_purpose_prompt = get_dr_prompt_orchestration_templates(
        DRPromptPurpose.NEXT_STEP_PURPOSE,
        ResearchType.DEEP,
        entity_types_string=all_entity_types,
        relationship_types_string=all_relationship_types,
        available_tools=available_tools,
    )
    orchestration_next_step_purpose_prompt = base_next_step_purpose_prompt.build(
        question=prompt_question,
        reasoning_result=reasoning_result,
        tool_calls=tool_calls_string,
    )

    purpose_tokens: list[str] = [""]
    purpose = ""

    if research_type in [ResearchType.THOUGHTFUL, ResearchType.DEEP]:

        try:

            write_custom_event(
                current_step_nr,
                ReasoningStart(),
                writer,
            )

            purpose_tokens, _, _ = run_with_timeout(
                TF_DR_TIMEOUT_LONG,
                lambda: stream_llm_answer(
                    llm=graph_config.tooling.primary_llm,
                    prompt=create_question_prompt(
                        decision_system_prompt,
                        orchestration_next_step_purpose_prompt,
                        uploaded_image_context=uploaded_image_context,
                    ),
                    event_name="basic_response",
                    writer=writer,
                    agent_answer_level=0,
                    agent_answer_question_num=0,
                    agent_answer_type="agent_level_answer",
                    timeout_override=TF_DR_TIMEOUT_LONG,
                    answer_piece=StreamingType.REASONING_DELTA.value,
                    ind=current_step_nr,
                    # max_tokens=None,
                ),
            )

            write_custom_event(
                current_step_nr,
                SectionEnd(),
                writer,
            )

            current_step_nr += 1

        except Exception as e:
            logger.error("Error in orchestration next step purpose.")
            raise e

        purpose = cast(str, merge_content(*purpose_tokens))

    elif research_type == ResearchType.FAST:
        purpose = f"Answering the question using the {next_tool_name}"

    if not next_tool_name:
        raise ValueError("The next step has not been defined. This should not happen.")

    return OrchestrationUpdate(
        tools_used=[next_tool_name],
        query_list=query_list or [],
        iteration_nr=iteration_nr,
        current_step_nr=current_step_nr,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="orchestrator",
                node_start_time=node_start_time,
            )
        ],
        plan_of_record=plan_of_record,
        remaining_time_budget=remaining_time_budget,
        iteration_instructions=[
            IterationInstructions(
                iteration_nr=iteration_nr,
                plan=plan_of_record.plan if plan_of_record else None,
                reasoning=reasoning_result,
                purpose=purpose,
            )
        ],
    )
