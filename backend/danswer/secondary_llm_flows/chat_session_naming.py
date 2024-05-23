from danswer.chat.chat_utils import combine_message_chain
from danswer.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from danswer.db.models import ChatMessage
from danswer.llm.exceptions import GenAIDisabledException
from danswer.llm.factory import get_default_llm
from danswer.llm.interfaces import LLM
from danswer.llm.utils import dict_based_prompt_to_langchain_prompt
from danswer.llm.utils import message_to_string
from danswer.prompts.chat_prompts import CHAT_NAMING
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_renamed_conversation_name(
    full_history: list[ChatMessage],
    llm: LLM | None = None,
) -> str:
    def get_chat_rename_messages(history_str: str) -> list[dict[str, str]]:
        messages = [
            {
                "role": "user",
                "content": CHAT_NAMING.format(chat_history=history_str),
            },
        ]
        return messages

    if llm is None:
        try:
            llm = get_default_llm()
        except GenAIDisabledException:
            # This may be longer than what the LLM tends to produce but is the most
            # clear thing we can do
            return full_history[0].message

    history_str = combine_message_chain(
        messages=full_history, token_limit=GEN_AI_HISTORY_CUTOFF
    )

    prompt_msgs = get_chat_rename_messages(history_str)

    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(prompt_msgs)
    new_name_raw = message_to_string(llm.invoke(filled_llm_prompt))

    new_name = new_name_raw.strip().strip(' "')

    logger.debug(f"New Session Name: {new_name}")

    return new_name
