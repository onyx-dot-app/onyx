# TODO: Notes for potential extensions and future improvements:
# 1. Allow tools that aren't search specific tools
# 2. Use user provided custom prompts

from collections.abc import Callable
from typing import cast

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import construct_message_history
from onyx.chat.llm_step import run_llm_step
from onyx.chat.llm_step import run_llm_step_pkt_generator
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.constants import MessageType
from onyx.deep_research.dr_mock_tools import get_clarification_tool_definitions
from onyx.deep_research.dr_mock_tools import get_orchestrator_tools
from onyx.deep_research.dr_mock_tools import RESEARCH_AGENT_TOOL_NAME
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_MESSAGE
from onyx.deep_research.dr_mock_tools import THINK_TOOL_RESPONSE_TOKEN_COUNT
from onyx.deep_research.utils import check_special_tool_calls
from onyx.deep_research.utils import create_think_tool_token_processor
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.utils import model_is_reasoning_model
from onyx.prompts.deep_research.orchestration_layer import CLARIFICATION_PROMPT
from onyx.prompts.deep_research.orchestration_layer import FINAL_REPORT_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT_REASONING
from onyx.prompts.deep_research.orchestration_layer import RESEARCH_PLAN_PROMPT
from onyx.prompts.deep_research.orchestration_layer import USER_FINAL_REPORT_QUERY
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import DeepResearchPlanDelta
from onyx.server.query_and_chat.streaming_models import DeepResearchPlanStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.fake_tools.research_agent import run_research_agent_calls
from onyx.tools.models import ToolCallInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_USER_MESSAGES_FOR_CONTEXT = 5
MAX_ORCHESTRATOR_CYCLES = 8


def generate_final_report(
    history: list[ChatMessageSimple],
    llm: LLM,
    token_counter: Callable[[str], int],
    state_container: ChatStateContainer,
    emitter: Emitter,
    user_identity: LLMUserIdentity | None,
) -> None:
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

    llm_step_result, _ = run_llm_step(
        emitter=emitter,
        history=final_report_history,
        tool_definitions=[],
        tool_choice=ToolChoiceOptions.NONE,
        llm=llm,
        turn_index=999,  # TODO
        citation_processor=DynamicCitationProcessor(),
        state_container=state_container,
        reasoning_effort=ReasoningEffort.LOW,
        final_documents=None,
        user_identity=user_identity,
    )

    final_report = llm_step_result.answer
    if final_report is None:
        raise ValueError("LLM failed to generate the final deep research report")

    state_container.set_answer_tokens(final_report)


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
) -> None:
    # Here for lazy load LiteLLM
    from onyx.llm.litellm_singleton.config import initialize_litellm

    # An approximate limit. In extreme cases it may still fail but this should allow deep research
    # to work in most cases.
    if llm.config.max_input_tokens < 25000:
        raise RuntimeError(
            "Cannot run Deep Research with an LLM that has less than 25,000 max input tokens"
        )

    initialize_litellm()

    available_tokens = llm.config.max_input_tokens

    llm_step_result: LlmStepResult | None = None

    # Filter tools to only allow web search, internal search, and open URL
    allowed_tool_names = {SearchTool.NAME, WebSearchTool.NAME, OpenURLTool.NAME}
    allowed_tools = [tool for tool in tools if tool.name in allowed_tool_names]

    #########################################################
    # CLARIFICATION STEP (optional)
    #########################################################
    if not skip_clarification:
        clarification_prompt = CLARIFICATION_PROMPT.format(
            current_datetime=get_current_llm_day_time(full_sentence=False)
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
            turn_index=0,
            # No citations in this step, it should just pass through all
            # tokens directly so initialized as an empty citation processor
            citation_processor=DynamicCitationProcessor(),
            state_container=state_container,
            final_documents=None,
            user_identity=user_identity,
        )

        if not llm_step_result.tool_calls:
            # Mark this turn as a clarification question
            state_container.set_is_clarification(True)

            emitter.emit(Packet(turn_index=0, obj=OverallStop(type="stop")))

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

    truncated_message_history = construct_message_history(
        system_prompt=system_prompt,
        custom_agent_prompt=None,
        simple_chat_history=simple_chat_history,
        reminder_message=None,
        project_files=None,
        available_tokens=available_tokens,
        last_n_user_messages=MAX_USER_MESSAGES_FOR_CONTEXT,
    )

    research_plan_generator = run_llm_step_pkt_generator(
        history=truncated_message_history,
        tool_definitions=[],
        tool_choice=ToolChoiceOptions.NONE,
        llm=llm,
        turn_index=0,
        # No citations in this step, it should just pass through all
        # tokens directly so initialized as an empty citation processor
        citation_processor=DynamicCitationProcessor(),
        state_container=state_container,
        final_documents=None,
        user_identity=user_identity,
    )

    while True:
        try:
            packet = next(research_plan_generator)
            # Translate AgentResponseStart/Delta packets to DeepResearchPlanStart/Delta
            if isinstance(packet.obj, AgentResponseStart):
                emitter.emit(
                    Packet(
                        turn_index=packet.turn_index,
                        obj=DeepResearchPlanStart(),
                    )
                )
            elif isinstance(packet.obj, AgentResponseDelta):
                emitter.emit(
                    Packet(
                        turn_index=packet.turn_index,
                        obj=DeepResearchPlanDelta(content=packet.obj.content),
                    )
                )
            else:
                # Pass through other packet types (e.g., ReasoningStart, ReasoningDelta, etc.)
                emitter.emit(packet)
        except StopIteration as e:
            llm_step_result, _ = e.value
            break
    llm_step_result = cast(LlmStepResult, llm_step_result)

    research_plan = llm_step_result.answer

    #########################################################
    # RESEARCH EXECUTION STEP
    #########################################################
    is_reasoning_model = model_is_reasoning_model(
        llm.config.model_name, llm.config.model_provider
    )

    orchestrator_prompt_template = (
        ORCHESTRATOR_PROMPT if not is_reasoning_model else ORCHESTRATOR_PROMPT_REASONING
    )

    token_count_prompt = orchestrator_prompt_template.format(
        current_datetime=get_current_llm_day_time(full_sentence=False),
        current_cycle_count=1,
        max_cycles=MAX_ORCHESTRATOR_CYCLES,
        research_plan=research_plan,
    )
    orchestration_tokens = token_counter(token_count_prompt)

    reasoning_cycles = 0
    for cycle in range(MAX_ORCHESTRATOR_CYCLES):
        research_agent_calls: list[ToolCallKickoff] = []

        orchestrator_prompt = orchestrator_prompt_template.format(
            current_datetime=get_current_llm_day_time(full_sentence=False),
            current_cycle_count=cycle,
            max_cycles=MAX_ORCHESTRATOR_CYCLES,
            research_plan=research_plan,
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
            turn_index=cycle + reasoning_cycles,
            # No citations in this step, it should just pass through all
            # tokens directly so initialized as an empty citation processor
            citation_processor=DynamicCitationProcessor(),
            state_container=state_container,
            final_documents=None,
            user_identity=user_identity,
            custom_token_processor=custom_processor,
        )
        if has_reasoned:
            reasoning_cycles += 1

        tool_calls = llm_step_result.tool_calls or []

        if not tool_calls and cycle == 0:
            raise RuntimeError(
                "Deep Research failed to generate any research tasks for the agents."
            )

        # TODO generate report if there are no tool calls and cycle is not 0

        most_recent_reasoning: str | None = None
        if tool_calls:
            special_tool_calls = check_special_tool_calls(tool_calls=tool_calls)

            if special_tool_calls.generate_report_tool_call:
                generate_final_report(
                    history=simple_chat_history,
                    llm=llm,
                    token_counter=token_counter,
                    state_container=state_container,
                    emitter=emitter,
                    user_identity=user_identity,
                )
                break
            elif special_tool_calls.think_tool_call:
                think_tool_call = special_tool_calls.think_tool_call
                # Only process the THINK_TOOL and skip all other tool calls
                # This will not actually get saved to the db as a tool call but we'll attach it to the tool(s) called after
                # it as if it were just a reasoning model doing it. In the chat history, because it happens in 2 steps,
                # we will show it as a separate message.
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
                reasoning_cycles += 1
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
                    generate_final_report(
                        history=simple_chat_history,
                        llm=llm,
                        token_counter=token_counter,
                        state_container=state_container,
                        emitter=emitter,
                        user_identity=user_identity,
                    )
                    break

                research_results = run_research_agent_calls(
                    research_agent_calls=research_agent_calls,
                    tools=allowed_tools,
                    emitter=emitter,
                    state_container=state_container,
                    llm=llm,
                    is_reasoning_model=is_reasoning_model,
                    token_counter=token_counter,
                    user_identity=user_identity,
                )

                for research_result in research_results:
                    tool_call_info = ToolCallInfo(
                        parent_tool_call_id=None,
                        turn_index=cycle + reasoning_cycles,
                        tab_index=0,
                        tool_name=tool_call.tool_name,
                        tool_call_id=tool_call.tool_call_id,
                        tool_id=999,  # TODO
                        reasoning_tokens=most_recent_reasoning,
                        tool_call_arguments=tool_call.tool_args,
                        tool_call_response=research_result.intermediate_report,
                        search_docs=research_result.search_docs,
                        generated_images=None,
                    )
                    state_container.add_tool_call(tool_call_info)

                    tool_call_message = tool_call.to_msg_str()
                    tool_call_token_count = token_counter(tool_call_message)

                    tool_call_msg = ChatMessageSimple(
                        message=tool_call_message,
                        token_count=tool_call_token_count,
                        message_type=MessageType.TOOL_CALL,
                        tool_call_id=tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(tool_call_msg)

                    tool_call_response_msg = ChatMessageSimple(
                        message=research_result.intermediate_report,
                        token_count=token_counter(research_result.intermediate_report),
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        tool_call_id=tool_call.tool_call_id,
                        image_files=None,
                    )
                    simple_chat_history.append(tool_call_response_msg)

            if not special_tool_calls.think_tool_call:
                most_recent_reasoning = None
        else:
            logger.warning("No tool calls found, this should not happen.")
            generate_final_report(
                history=simple_chat_history,
                llm=llm,
                token_counter=token_counter,
                state_container=state_container,
                emitter=emitter,
                user_identity=user_identity,
            )
