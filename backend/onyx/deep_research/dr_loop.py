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
from onyx.prompts.deep_research.orchestration_layer import CLARIFICATION_PROMPT
from onyx.prompts.prompt_utils import get_current_llm_day_time
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_MESSAGES_FOR_CLARIFICATION = 5


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

    if llm.config.max_input_tokens < 25000:
        raise RuntimeError(
            "Cannot run Deep Research with an LLM that has less than 25,000 max input tokens"
        )

    initialize_litellm()

    available_tokens = llm.config.max_input_tokens
    current_tool_call_index = 0

    llm_step_result: LlmStepResult | None = None

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
            last_n_user_messages=MAX_MESSAGES_FOR_CLARIFICATION,
        )

        step_generator = run_llm_step(
            history=truncated_message_history,
            tool_definitions=get_clarification_tool_definitions(),
            tool_choice=ToolChoiceOptions.AUTO,
            llm=llm,
            turn_index=current_tool_call_index,
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
                llm_step_result, current_tool_call_index = e.value
                break

        # Type narrowing: generator always returns a result, so this can't be None
        llm_step_result = cast(LlmStepResult, llm_step_result)

        if not llm_step_result.tool_calls:
            # Mark this turn as a clarification question
            state_container.set_is_clarification(True)

            emitter.emit(
                Packet(turn_index=current_tool_call_index, obj=OverallStop(type="stop"))
            )

            # If a clarification is asked, we need to end this turn and wait on user input
            return
