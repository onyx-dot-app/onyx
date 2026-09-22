from collections.abc import Sequence

from onyx.chat.history_translation import translate_history_to_native_messages
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.db.models import ChatMessage
from onyx.llm.inference import run_inference
from onyx.llm.interfaces import LLM
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
    chat_history: list[ChatMessageSimple],
    llm: LLM,
) -> str:
    system_prompt = ChatMessageSimple(
        message=CHAT_NAMING_SYSTEM_PROMPT,
        token_count=100,
        message_type=MessageType.SYSTEM,
    )

    reminder_prompt = ChatMessageSimple(
        message=CHAT_NAMING_REMINDER,
        token_count=100,
        message_type=MessageType.USER_REMINDER,
    )

    complete_message_history = [system_prompt] + chat_history + [reminder_prompt]

    llm_facing_history = translate_history_to_native_messages(
        complete_message_history, llm.config
    )

    new_name_raw = run_inference(
        llm=llm,
        messages=llm_facing_history,
        output_type=str,
        flow=LLMFlow.CHAT_SESSION_NAMING,
    )

    return new_name_raw.strip().strip('"')
