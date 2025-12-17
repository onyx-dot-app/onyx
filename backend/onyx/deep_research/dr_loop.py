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
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.constants import MessageType
from onyx.deep_research.dr_mock_tools import get_clarification_tool_definitions
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.utils import model_is_reasoning_model
from onyx.prompts.deep_research.orchestration_layer import CLARIFICATION_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT
from onyx.prompts.deep_research.orchestration_layer import ORCHESTRATOR_PROMPT_REASONING
from onyx.prompts.deep_research.orchestration_layer import RESEARCH_PLAN_PROMPT
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import DeepResearchPlanDelta
from onyx.server.query_and_chat.streaming_models import DeepResearchPlanStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import WebSearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_USER_MESSAGES_FOR_CONTEXT = 5
MAX_ORCHESTRATOR_CYCLES = 8


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
    [tool for tool in tools if tool.name in allowed_tool_names]

    #########################################################
    # CLARIFICATION STEP (optional)
    #########################################################
    if not skip_clarification:
        clarification_prompt = CLARIFICATION_PROMPT.format(
            current_datetime=get_current_llm_day_time()
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

        step_generator = run_llm_step(
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

        # Consume the generator, emitting packets and capturing the final result
        while True:
            try:
                packet = next(step_generator)
                emitter.emit(packet)
            except StopIteration as e:
                llm_step_result, _ = e.value
                break

        # Type narrowing: generator always returns a result, so this can't be None
        llm_step_result = cast(LlmStepResult, llm_step_result)

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
            current_datetime=get_current_llm_day_time()
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

    research_plan_generator = run_llm_step(
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
        current_datetime=get_current_llm_day_time(),
        current_cycle_count=1,
        max_cycles=MAX_ORCHESTRATOR_CYCLES,
        research_plan=research_plan,
    )
    orchestration_tokens = token_counter(token_count_prompt)

    for cycle in range(MAX_ORCHESTRATOR_CYCLES):
        orchestrator_prompt = orchestrator_prompt_template.format(
            current_datetime=get_current_llm_day_time(),
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

        research_plan_generator = run_llm_step(
            history=truncated_message_history,
            tool_definitions=[],
            tool_choice=ToolChoiceOptions.AUTO,
            llm=llm,
            turn_index=cycle,
            # No citations in this step, it should just pass through all
            # tokens directly so initialized as an empty citation processor
            citation_processor=DynamicCitationProcessor(),
            state_container=state_container,
            final_documents=None,
            user_identity=user_identity,
        )
