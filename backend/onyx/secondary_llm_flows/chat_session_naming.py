from collections.abc import Sequence

from onyx.configs.constants import MessageType
from onyx.context.messages import PromptMetadata, prepare_model_messages
from onyx.db.models import ChatMessage
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    Message,
    ReasoningEffort,
    SystemMessage,
    UserMessage,
)
from onyx.prompts.chat_prompts import CHAT_NAMING_REMINDER, CHAT_NAMING_SYSTEM_PROMPT
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger

logger = setup_logger()

DEFAULT_CHAT_SESSION_NAME = "New Chat"
FALLBACK_CHAT_SESSION_NAME_LENGTH = 40


def get_fallback_chat_session_name(chat_history: Sequence[ChatMessage]) -> str:
    user_message = next(
        (
            message.message.strip()
            for message in chat_history
            if message.message_type == MessageType.USER and message.message.strip()
        ),
        "",
    )
    if not user_message:
        return DEFAULT_CHAT_SESSION_NAME
    if len(user_message) <= FALLBACK_CHAT_SESSION_NAME_LENGTH:
        return user_message
    return user_message[:FALLBACK_CHAT_SESSION_NAME_LENGTH].rstrip() + "..."


def generate_chat_session_name(
    chat_history: list[Message],
    llm: LLM,
) -> str:
    system_prompt = SystemMessage(
        content=CHAT_NAMING_SYSTEM_PROMPT, metadata=PromptMetadata(token_count=100)
    )

    reminder_prompt = UserMessage(
        content=CHAT_NAMING_REMINDER,
        metadata=PromptMetadata(token_count=100, is_reminder=True),
    )

    complete_message_history = [system_prompt] + chat_history + [reminder_prompt]

    response = llm.invoke(
        GenerationRequest(
            messages=prepare_model_messages(complete_message_history, llm.config),
            options=GenerationOptions(reasoning_effort=ReasoningEffort.OFF),
        ),
        context=GenerationContext(flow=LLMFlow.CHAT_SESSION_NAMING),
    )
    new_name_raw = response.text

    return new_name_raw.strip().strip('"')
