from langchain.schema import BaseMessage
from langchain.schema import HumanMessage
from langchain.schema import SystemMessage

from onyx.chat.chat_utils import combine_message_chain
from onyx.chat.prompt_builder.utils import translate_onyx_msg_to_langchain
from onyx.configs.chat_configs import DISABLE_LLM_CHOOSE_SEARCH
from onyx.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from onyx.context.search.enums import SearchType
from onyx.db.models import ChatMessage
from onyx.llm.interfaces import LLM
from onyx.llm.models import PreviousMessage
from onyx.llm.utils import dict_based_prompt_to_langchain_prompt
from onyx.llm.utils import message_to_string
from onyx.prompts.chat_prompts import AggressiveSearchTemplateParams
from onyx.prompts.chat_prompts import build_aggressive_search_template
from onyx.prompts.chat_prompts import NO_SEARCH
from onyx.prompts.chat_prompts import REQUIRE_SEARCH_HINT
from onyx.prompts.chat_prompts import REQUIRE_SEARCH_SYSTEM_MSG
from onyx.prompts.chat_prompts import SKIP_SEARCH
from onyx.utils.logger import setup_logger


logger = setup_logger()


def check_if_need_search_multi_message(
    query_message: ChatMessage,
    history: list[ChatMessage],
    llm: LLM,
) -> bool:
    # Retrieve on start or when choosing is globally disabled
    if not history or DISABLE_LLM_CHOOSE_SEARCH:
        return True

    prompt_msgs: list[BaseMessage] = [SystemMessage(content=REQUIRE_SEARCH_SYSTEM_MSG)]
    prompt_msgs.extend([translate_onyx_msg_to_langchain(msg) for msg in history])

    last_query = query_message.message

    prompt_msgs.append(HumanMessage(content=f"{last_query}\n\n{REQUIRE_SEARCH_HINT}"))

    model_out = message_to_string(llm.invoke(prompt_msgs))

    if (NO_SEARCH.split()[0] + " ").lower() in model_out.lower():
        return False

    return True


def check_if_need_search(
    query: str,
    history: list[PreviousMessage],
    llm: LLM,
    search_type: SearchType = SearchType.KEYWORD,
) -> bool:
    """
    Determines if search is needed based on query and history.

    Args:
        query: The user's query
        history: List of previous messages
        llm: The language model to use for prediction
        search_type: INTERNET enum for internetsearch. Keyword and semantic are treated the same.

    Returns:
        True if search is needed, False otherwise
    """
    # Choosing is globally disabled, use search (only for internal search)
    if search_type == SearchType.KEYWORD and DISABLE_LLM_CHOOSE_SEARCH:
        return True

    # Select log message based on search type
    if search_type == SearchType.INTERNET:
        log_message = "Run internet search prediction"
    else:
        log_message = "Run search prediction"

    history_str = combine_message_chain(
        messages=history, token_limit=GEN_AI_HISTORY_CUTOFF
    )

    # Note: Internet and internal search use the same prompt
    prompt_template = build_aggressive_search_template(
        AggressiveSearchTemplateParams(chat_history=history_str, final_query=query)
    )
    prompt_msgs = [
        {
            "role": "user",
            "content": prompt_template,
        },
    ]

    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(prompt_msgs)
    search_output = message_to_string(llm.invoke(filled_llm_prompt))

    logger.debug(f"{log_message}: {search_output}")

    return (SKIP_SEARCH.split()[0]).lower() not in search_output.lower()
