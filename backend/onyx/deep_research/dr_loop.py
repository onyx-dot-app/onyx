# TODO: Notes for potential extensions and future improvements:
# 1. Allow tools that aren't search specific tools
# 2. Use user provided custom prompts
# 3. Save the plan for replay

from collections.abc import Callable
from typing import cast

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import CitationMapping
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.llm_step import run_llm_step
from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.constants import MessageType
from onyx.db.tools import get_tool_by_name
from onyx.deep_research.dr_mock_tools import get_clarification_tool_definitions
from onyx.deep_research.dr_mock_tools import get_orchestrator_tools
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_DB_NAME
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_TOOL_NAME
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_MESSAGE
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_TOKEN_COUNT
from onyx.deep_research.utils import check_special_tool_calls
from onyx.deep_research.utils import create_think_tool_token_processor
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.utils import model_is_reasoning_model
from onyx.prompts.deep_research.orchestration_layer import CLARIFICATION_PROMPT
from onyx.prompts.deep_research.orchestration_layer import FINAL_REPORT_PROMPT
from onyx.prompts.deep_research.orchestration_layer import (
    INTERNAL_SEARCH_CLARIFICATION_GUIDANCE,
)
from onyx.prompts.deep_research.orchestration_layer import (
    INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE,
)
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT_REASONING
from onyx.prompts.deep_research.orchestration_layer import RESEARCH_PLAN_PROMPT
from onyx.prompts.deep_research.orchestration_layer import RESEARCH_PLAN_REMINDER
from onyx.prompts.deep_research.orchestration_layer import USER_FINAL_REPORT_QUERY
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import DeepResearchPlanDelta
from onyx.server.query_and_chat.streaming_models import DeepResearchPlanStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.server.query_and_chat.streaming_models import TopLevelBranching
from onyx.tools.fake_tools.research_agent import run_research_agent_calls
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.tracing.framework.create import function_span
from onyx.tracing.framework.create import trace
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

MAX_USER_MESSAGES_FOR_CONTEXT = 5
MAX_FINAL_REPORT_TOKENS = 20000

# Might be something like (this gives a lot of leeway for change but typically the models don't do this):
# 0. Research topics 1-3
# 1. Think
# 2. Research topics 4-5
# 3. Think
# 4. Research topics 6 + something new or different from the plan
# 5. Think
# 6. Research, possibly something new or different from the plan
# 7. Think
# 8. Generate report
MAX_ORCHESTRATOR_CYCLES = 8

# Similar but without the 4 thinking tool calls
MAX_ORCHESTRATOR_CYCLES_REASONING = 4


def generate_final_report(
    history: list[ChatMessageSimple],
    llm: LLM,
    token_counter: Callable[[str], int],
    state_container: ChatStateContainer,
    emitter: Emitter,
    turn_index: int,
    citation_mapping: CitationMapping,
    user_identity: LLMUserIdentity | None,
    saved_reasoning: str | None = None,
) -> bool:
    """Generate the final research report.

    Returns:
        bool: True if reasoning occurred during report generation (turn_index was incremented),
              False otherwise.
    """
    with function_span("generate_report") as span:
        span.span_data.input = f"history_length={len(history)}, turn_index={turn_index}"
        final_report_prompt = FINAL_REPORT_PROMPT.format(
            current_datetime=get_current_llm_day_time(full_sentence=False),
        )
        system_prompt = ChatMessageSimple(
            message=final_report_prompt,
            token_count=token_counter(final_report_prompt),
            message_type=MessageType.SYSTEM,
        )
        reminder_message = ChatMessageSimple(
            message=USER_FINAL_REPORT_QUERY,
            token_count=token_counter(USER_FINAL_REPORT_QUERY),
            message_type=MessageType.USER,
        )
        final_report_history = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=history,
            reminder_message=reminder_message,
            project_files=None,
            available_tokens=llm.config.max_input_tokens,
        )

        citation_processor = DynamicCitationProcessor()
        citation_processor.update_citation_mapping(citation_mapping)

        # Only passing in the cited documents as the whole list would be too long
        final_documents = list(citation_processor.citation_to_doc.values())

        llm_step_result, has_reasoned = run_llm_step(
            emitter=emitter,
            history=final_report_history,
            tool_definitions=[],
            tool_choice=ToolChoiceOptions.NONE,
            llm=llm,
            placement=Placement(turn_index=turn_index),
            citation_processor=citation_processor,
            state_container=state_container,
            final_documents=final_documents,
            user_identity=user_identity,
            max_tokens=MAX_FINAL_REPORT_TOKENS,
            is_deep_research=True,
        )

        final_report = llm_step_result.answer
        if final_report is None:
            raise ValueError("LLM failed to generate the final deep research report")

        if saved_reasoning:
            # The reasoning we want to save with the message is more about calling this
            # generate report and why it's done. Also some models don't have reasoning
            # but we'd still want to capture the reasoning from the think_tool of theprevious turn.
            state_container.set_reasoning_tokens(saved_reasoning)

        span.span_data.output = final_report if final_report else None
        return has_reasoned


@log_function_time(print_only=True)
def run_deep_research_llm_loop(
    emitter: Emitter,
    state_container: ChatStateContainer,
    simple_chat_history: list[ChatMessageSimple],
    tools: list[Tool],
    custom_agent_prompt: str | None,
    llm: LLM,
    token_counter: Callable[[str], int],
    db_session: Session,
    skip_clarification: bool = False,
    user_identity: LLMUserIdentity | None = None,
    chat_session_id: str | None = None,
) -> None:
    with trace(
        "run_deep_research_llm_loop",
        group_id=chat_session_id,
        metadata={
            "tenant_id": get_current_tenant_id(),
            "chat_session_id": chat_session_id,
        },
    ):
        # Here for lazy load LiteLLM
        from onyx.llm.litellm_singleton.config import initialize_litellm

        # An approximate limit. In extreme cases it may still fail but this should allow deep research
        # to work in most cases.
        if llm.config.max_input_tokens < 50000:
            raise RuntimeError(
                "Cannot run Deep Research with an LLM that has less than 50,000 max input tokens"
            )

        initialize_litellm()

        available_tokens = llm.config.max_input_tokens

        llm_step_result: LlmStepResult | None = None

        # Filter tools to only allow web search, internal search, and open URL
        allowed_tool_names = {SearchTool.NAME, WebSearchTool.NAME, OpenURLTool.NAME}
        allowed_tools = [tool for tool in tools if tool.name in allowed_tool_names]
        include_internal_search_tunings = SearchTool.NAME in allowed_tool_names
        orchestrator_start_turn_index = 1

        #########################################################
        # CLARIFICATION STEP (optional)
        #########################################################
        internal_search_clarification_guidance = (
            INTERNAL_SEARCH_CLARIFICATION_GUIDANCE
            if include_internal_search_tunings
            else ""
        )
        if not skip_clarification:
            clarification_prompt = CLARIFICATION_PROMPT.format(
                current_datetime=get_current_llm_day_time(full_sentence=False),
                internal_search_clarification_guidance=internal_search_clarification_guidance,
            )
            system_prompt = ChatMessageSimple(
                message=clarification_prompt,
                token_count=300,  # Skips the exact token count but has enough leeway
                message_type=MessageType.SYSTEM,
            )

            truncated_message_history = construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=None,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                project_files=None,
                available_tokens=available_tokens,
                last_n_user_messages=MAX_USER_MESSAGES_FOR_CONTEXT,
            )

            llm_step_result, _ = run_llm_step(
                emitter=emitter,
                history=truncated_message_history,
                tool_definitions=get_clarification_tool_definitions(),
                tool_choice=ToolChoiceOptions.AUTO,
                llm=llm,
                placement=Placement(turn_index=0),
                # No citations in this step, it should just pass through all
                # tokens directly so initialized as an empty citation processor
                citation_processor=None,
                state_container=state_container,
                final_documents=None,
                user_identity=user_identity,
                is_deep_research=True,
            )

            if not llm_step_result.tool_calls:
                # Mark this turn as a clarification question
                state_container.set_is_clarification(True)

                emitter.emit(
                    Packet(
                        placement=Placement(turn_index=0), obj=OverallStop(type="stop")
                    )
                )

                # If a clarification is asked, we need to end this turn and wait on user input
                return

        #########################################################
        # RESEARCH PLAN STEP
        #########################################################
        system_prompt = ChatMessageSimple(
            message=RESEARCH_PLAN_PROMPT.format(
                current_datetime=get_current_llm_day_time(full_sentence=False)
            ),
            token_count=300,
            message_type=MessageType.SYSTEM,
        )
        reminder_message = ChatMessageSimple(
            message=RESEARCH_PLAN_REMINDER,
            token_count=100,
            message_type=MessageType.USER,
        )
        truncated_message_history = construct_message_history(
            system_prompt=system_prompt,
            custom_agent_prompt=None,
            simple_chat_history=simple_chat_history + [reminder_message],
            reminder_message=None,
            project_files=None,
            available_tokens=available_tokens,
            last_n_user_messages=MAX_USER_MESSAGES_FOR_CONTEXT + 1,
        )

        research_plan_generator = run_llm_step_pkt_generator(
            history=truncated_message_history,
            tool_definitions=[],
            tool_choice=ToolChoiceOptions.NONE,
            llm=llm,
            placement=Placement(turn_index=0),
            citation_processor=None,
            state_container=state_container,
            final_documents=None,
            user_identity=user_identity,
            is_deep_research=True,
        )

        while True:
            try:
                packet = next(research_plan_generator)
                # Translate AgentResponseStart/Delta packets to DeepResearchPlanStart/Delta
                # The LLM response from this prompt is the research plan
                if isinstance(packet.obj, AgentResponseStart):
                    emitter.emit(
                        Packet(
                            placement=packet.placement,
                            obj=DeepResearchPlanStart(),
                        )
                    )
                elif isinstance(packet.obj, AgentResponseDelta):
                    emitter.emit(
                        Packet(
                            placement=packet.placement,
                            obj=DeepResearchPlanDelta(content=packet.obj.content),
                        )
                    )
                else:
                    # Pass through other packet types (e.g., ReasoningStart, ReasoningDelta, etc.)
                    emitter.emit(packet)
            except StopIteration as e:
                llm_step_result, reasoned = e.value
                emitter.emit(
                    Packet(
                        # Marks the last turn end which should be the plan generation
                        placement=Placement(
                            turn_index=1 if reasoned else 0,
                        ),
                        obj=SectionEnd(),
                    )
                )
                if reasoned:
                    orchestrator_start_turn_index += 1
                break
        llm_step_result = cast(LlmStepResult, llm_step_result)

        research_plan = llm_step_result.answer

        #########################################################
        # RESEARCH EXECUTION STEP
        #########################################################
        is_reasoning_model = model_is_reasoning_model(
            llm.config.model_name, llm.config.model_provider
        )

        max_orchestrator_cycles = (
            MAX_ORCHESTRATOR_CYCLES
            if not is_reasoning_model
            else MAX_ORCHESTRATOR_CYCLES_REASONING
        )

        orchestrator_prompt_template = (
            ORCHESTRATOR_PROMPT
            if not is_reasoning_model
            else ORCHESTRATOR_PROMPT_REASONING
        )

        internal_search_research_task_guidance = (
            INTERNAL_SEARCH_RESEARCH_TASK_GUIDANCE
            if include_internal_search_tunings
            else ""
        )
        token_count_prompt = orchestrator_prompt_template.format(
            current_datetime=get_current_llm_day_time(full_sentence=False),
            current_cycle_count=1,
            max_cycles=max_orchestrator_cycles,
            research_plan=research_plan,
            internal_search_research_task_guidance=internal_search_research_task_guidance,
        )
        orchestration_tokens = token_counter(token_count_prompt)

        reasoning_cycles = 0
        most_recent_reasoning: str | None = None
        citation_mapping: CitationMapping = {}
        final_turn_index: int = (
            orchestrator_start_turn_index  # Track the final turn_index for stop packet
        )
        for cycle in range(max_orchestrator_cycles):
            if cycle == max_orchestrator_cycles - 1:
                # If it's the last cycle, forcibly generate the final report
                report_turn_index = (
                    orchestrator_start_turn_index + cycle + reasoning_cycles
                )
                report_reasoned = generate_final_report(
                    history=simple_chat_history,
                    llm=llm,
                    token_counter=token_counter,
                    state_container=state_container,
                    emitter=emitter,
                    turn_index=report_turn_index,
                    citation_mapping=citation_mapping,
                    user_identity=user_identity,
                )
                # Update final_turn_index: base + 1 for the report itself + 1 if reasoning occurred
                final_turn_index = report_turn_index + (1 if report_reasoned else 0)
                break

            research_agent_calls: list[ToolCallKickoff] = []

            orchestrator_prompt = orchestrator_prompt_template.format(
                current_datetime=get_current_llm_day_time(full_sentence=False),
                current_cycle_count=cycle,
                max_cycles=max_orchestrator_cycles,
                research_plan=research_plan,
                internal_search_research_task_guidance=internal_search_research_task_guidance,
            )

            system_prompt = ChatMessageSimple(
                message=orchestrator_prompt,
                token_count=orchestration_tokens,
                message_type=MessageType.SYSTEM,
            )

            truncated_message_history = construct_message_history(
                system_prompt=system_prompt,
                custom_agent_prompt=None,
                simple_chat_history=simple_chat_history,
                reminder_message=None,
                project_files=None,
                available_tokens=available_tokens,
                last_n_user_messages=MAX_USER_MESSAGES_FOR_CONTEXT,
            )

            # Use think tool processor for non-reasoning models to convert
            # think_tool calls to reasoning content
            custom_processor = (
                create_think_tool_token_processor() if not is_reasoning_model else None
            )

            llm_step_result, has_reasoned = run_llm_step(
                emitter=emitter,
                history=truncated_message_history,
                tool_definitions=get_orchestrator_tools(
                    include_think_tool=not is_reasoning_model
                ),
                tool_choice=ToolChoiceOptions.REQUIRED,
                llm=llm,
                placement=Placement(
                    turn_index=orchestrator_start_turn_index + cycle + reasoning_cycles
                ),
                # No citations in this step, it should just pass through all
                # tokens directly so initialized as an empty citation processor
                citation_processor=DynamicCitationProcessor(),
                state_container=state_container,
                final_documents=None,
                user_identity=user_identity,
                custom_token_processor=custom_processor,
                is_deep_research=True,
            )
            if has_reasoned:
                reasoning_cycles += 1

            tool_calls = llm_step_result.tool_calls or []

            if not tool_calls and cycle == 0:
                raise RuntimeError(
                    "Deep Research failed to generate any research tasks for the agents."
                )

            if not tool_calls:
                # Basically hope that this is an infrequent occurence and hopefully multiple research
                # cycles have already ran
                logger.warning("No tool calls found, this should not happen.")
                report_turn_index = (
                    orchestrator_start_turn_index + cycle + reasoning_cycles
                )
                report_reasoned = generate_final_report(
                    history=simple_chat_history,
                    llm=llm,
                    token_counter=token_counter,
                    state_container=state_container,
                    emitter=emitter,
                    turn_index=report_turn_index,
                    citation_mapping=citation_mapping,
                    user_identity=user_identity,
                )
                final_turn_index = report_turn_index + (1 if report_reasoned else 0)
                break

            special_tool_calls = check_special_tool_calls(tool_calls=tool_calls)

            if special_tool_calls.generate_report_tool_call:
                report_turn_index = (
                    special_tool_calls.generate_report_tool_call.placement.turn_index
                )
                report_reasoned = generate_final_report(
                    history=simple_chat_history,
                    llm=llm,
                    token_counter=token_counter,
                    state_container=state_container,
                    emitter=emitter,
                    turn_index=report_turn_index,
                    citation_mapping=citation_mapping,
                    user_identity=user_identity,
                    saved_reasoning=most_recent_reasoning,
                )
                final_turn_index = report_turn_index + (1 if report_reasoned else 0)
                break
            elif special_tool_calls.think_tool_call:
                think_tool_call = special_tool_calls.think_tool_call
                # Only process the THINK_TOOL and skip all other tool calls
                # This will not actually get saved to the db as a tool call but we'll attach it to the tool(s) called after
                # it as if it were just a reasoning model doing it. In the chat history, because it happens in 2 steps,
                # we will show it as a separate message.
                # NOTE: This does not need to increment the reasoning cycles because the custom token processor causes
                # the LLM step to handle this
                with function_span("think_tool") as span:
                    span.span_data.input = str(think_tool_call.tool_args)
                    most_recent_reasoning = state_container.reasoning_tokens
                    tool_call_message = think_tool_call.to_msg_str()

                    think_tool_msg = ChatMessageSimple(
                        message=tool_call_message,
                        token_count=token_counter(tool_call_message),
                        message_type=MessageType.TOOL_CALL,
                        tool_call_id=think_tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(think_tool_msg)

                    think_tool_response_msg = ChatMessageSimple(
                        message=THINK_TOOL_RESPONSE_MESSAGE,
                        token_count=THINK_TOOL_RESPONSE_TOKEN_COUNT,
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        tool_call_id=think_tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(think_tool_response_msg)
                    span.span_data.output = THINK_TOOL_RESPONSE_MESSAGE
                continue
            else:
                for tool_call in tool_calls:
                    if tool_call.tool_name != RESEARCH_AGENT_TOOL_NAME:
                        logger.warning(f"Unexpected tool call: {tool_call.tool_name}")
                        continue

                    research_agent_calls.append(tool_call)

                if not research_agent_calls:
                    logger.warning(
                        "No research agent tool calls found, this should not happen."
                    )
                    report_turn_index = (
                        orchestrator_start_turn_index + cycle + reasoning_cycles
                    )
                    report_reasoned = generate_final_report(
                        history=simple_chat_history,
                        llm=llm,
                        token_counter=token_counter,
                        state_container=state_container,
                        emitter=emitter,
                        turn_index=report_turn_index,
                        citation_mapping=citation_mapping,
                        user_identity=user_identity,
                    )
                    final_turn_index = report_turn_index + (1 if report_reasoned else 0)
                    break

                if len(research_agent_calls) > 1:
                    emitter.emit(
                        Packet(
                            placement=Placement(
                                turn_index=research_agent_calls[0].placement.turn_index
                            ),
                            obj=TopLevelBranching(
                                num_parallel_branches=len(research_agent_calls)
                            ),
                        )
                    )

                research_results = run_research_agent_calls(
                    # The tool calls here contain the placement information
                    research_agent_calls=research_agent_calls,
                    parent_tool_call_ids=[
                        tool_call.tool_call_id for tool_call in tool_calls
                    ],
                    tools=allowed_tools,
                    emitter=emitter,
                    state_container=state_container,
                    llm=llm,
                    is_reasoning_model=is_reasoning_model,
                    token_counter=token_counter,
                    citation_mapping=citation_mapping,
                    user_identity=user_identity,
                )

                citation_mapping = research_results.citation_mapping

                for tab_index, report in enumerate(
                    research_results.intermediate_reports
                ):
                    if report is None:
                        # The LLM will not see that this research was even attempted, it may try
                        # something similar again but this is not bad.
                        logger.error(
                            f"Research agent call at tab_index {tab_index} failed, skipping"
                        )
                        continue

                    current_tool_call = research_agent_calls[tab_index]
                    tool_call_info = ToolCallInfo(
                        parent_tool_call_id=None,
                        turn_index=orchestrator_start_turn_index
                        + cycle
                        + reasoning_cycles,
                        tab_index=tab_index,
                        tool_name=current_tool_call.tool_name,
                        tool_call_id=current_tool_call.tool_call_id,
                        tool_id=get_tool_by_name(
                            tool_name=RESEARCH_AGENT_DB_NAME, db_session=db_session
                        ).id,
                        reasoning_tokens=llm_step_result.reasoning
                        or most_recent_reasoning,
                        tool_call_arguments=current_tool_call.tool_args,
                        tool_call_response=report,
                        search_docs=None,  # Intermediate docs are not saved/shown
                        generated_images=None,
                    )
                    state_container.add_tool_call(tool_call_info)

                    tool_call_message = current_tool_call.to_msg_str()
                    tool_call_token_count = token_counter(tool_call_message)

                    tool_call_msg = ChatMessageSimple(
                        message=tool_call_message,
                        token_count=tool_call_token_count,
                        message_type=MessageType.TOOL_CALL,
                        tool_call_id=current_tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(tool_call_msg)

                    tool_call_response_msg = ChatMessageSimple(
                        message=report,
                        token_count=token_counter(report),
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        tool_call_id=current_tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(tool_call_response_msg)

            # If it reached this point, it did not call reasoning, so here we wipe it to not save it to multiple turns
            most_recent_reasoning = None

        emitter.emit(
            Packet(
                placement=Placement(turn_index=final_turn_index),
                obj=OverallStop(type="stop"),
            )
        )
