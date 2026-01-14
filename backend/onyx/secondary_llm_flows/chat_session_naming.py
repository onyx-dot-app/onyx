from onyx.chat.llm_step import translate_history_to_llm_format
from onyx.chat.models import ChatMessageSimple
from onyx.configs.constants import MessageType
from onyx.llm.interfaces import LLM
from onyx.llm.models import ReasoningEffort
from onyx.llm.utils import llm_response_to_string
from onyx.prompts.chat_prompts import CHAT_NAMING_REMINDER
from onyx.prompts.chat_prompts import CHAT_NAMING_SYSTEM_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
        message_type=MessageType.USER,
    )

    complete_message_history = [system_prompt] + chat_history + [reminder_prompt]

    llm_facing_history = translate_history_to_llm_format(
        complete_message_history, llm.config
    )
    new_name_raw = llm_response_to_string(
        llm.invoke(llm_facing_history, reasoning_effort=ReasoningEffort.OFF)
    )

    return new_name_raw.strip().strip('"')
