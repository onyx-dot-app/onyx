from sqlalchemy.orm import Session

from onyx.chat.models import PromptConfig
from onyx.configs.model_configs import GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS
from onyx.db.models import Persona
from onyx.db.search_settings import get_multilingual_expansion
from onyx.llm.factory import get_llm_config_for_persona
from onyx.llm.interfaces import LLMConfig
from onyx.llm.utils import check_number_of_tokens
from onyx.prompts.token_counts import ADDITIONAL_INFO_TOKEN_CNT
from onyx.prompts.token_counts import (
    CHAT_USER_PROMPT_WITH_CONTEXT_OVERHEAD_TOKEN_CNT,
)
from onyx.prompts.token_counts import CITATION_REMINDER_TOKEN_CNT
from onyx.prompts.token_counts import CITATION_STATEMENT_TOKEN_CNT
from onyx.prompts.token_counts import LANGUAGE_HINT_TOKEN_CNT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_prompt_tokens(prompt_config: PromptConfig) -> int:
    # Note: currently custom prompts do not allow datetime aware, only default prompts
    return (
        check_number_of_tokens(prompt_config.default_behavior_system_prompt)
        + check_number_of_tokens(prompt_config.reminder)
        + CHAT_USER_PROMPT_WITH_CONTEXT_OVERHEAD_TOKEN_CNT
        + CITATION_STATEMENT_TOKEN_CNT
        + CITATION_REMINDER_TOKEN_CNT
        + (LANGUAGE_HINT_TOKEN_CNT if get_multilingual_expansion() else 0)
        + (ADDITIONAL_INFO_TOKEN_CNT if prompt_config.datetime_aware else 0)
    )


# buffer just to be safe so that we don't overflow the token limit due to
# a small miscalculation
_MISC_BUFFER = 40


def compute_max_document_tokens(
    prompt_config: PromptConfig,
    llm_config: LLMConfig,
    actual_user_input: str | None = None,
    tool_token_count: int = 0,
) -> int:
    """Estimates the number of tokens available for context documents. Formula is roughly:

    (
        model_context_window - reserved_output_tokens - prompt_tokens
        - (actual_user_input OR reserved_user_message_tokens) - buffer (just to be safe)
    )

    The actual_user_input is used at query time. If we are calculating this before knowing the exact input (e.g.
    if we're trying to determine if the user should be able to select another document) then we just set an
    arbitrary "upper bound".
    """
    # if we can't find a number of tokens, just assume some common default
    prompt_tokens = get_prompt_tokens(prompt_config)

    user_input_tokens = (
        check_number_of_tokens(actual_user_input)
        if actual_user_input is not None
        else GEN_AI_SINGLE_USER_MESSAGE_EXPECTED_MAX_TOKENS
    )

    return (
        llm_config.max_input_tokens
        - prompt_tokens
        - user_input_tokens
        - tool_token_count
        - _MISC_BUFFER
    )


def compute_max_document_tokens_for_persona(
    persona: Persona,
    db_session: Session,
    actual_user_input: str | None = None,
) -> int:
    # Use the persona directly since prompts are now embedded
    # Access to persona is assumed to have been verified already
    return compute_max_document_tokens(
        prompt_config=PromptConfig.from_model(persona, db_session=db_session),
        llm_config=get_llm_config_for_persona(persona=persona, db_session=db_session),
        actual_user_input=actual_user_input,
    )
