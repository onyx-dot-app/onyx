from ee.onyx.prompts.search_flow_classification import CHAT_CLASS
from ee.onyx.prompts.search_flow_classification import SEARCH_CHAT_PROMPT
from ee.onyx.prompts.search_flow_classification import SEARCH_CLASS
from onyx.llm.interfaces import LLM
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


@log_function_time(print_only=True)
def classify_is_search_flow(
    query: str,
    llm: LLM,
) -> bool:
    messages: LanguageModelInput = [
        UserMessage(content=SEARCH_CHAT_PROMPT.format(user_query=query))
    ]
    response = llm.invoke(
        prompt=messages,
        reasoning_effort=ReasoningEffort.OFF,
        # Nothing can happen in the UI until this call finishes so we need to be aggressive with the timeout
        timeout_override=2,
        # Well more than necessary but just to ensure completion and in case it succeeds with classifying but
        # ends up rambling
        max_tokens=20,
    )

    content = llm_response_to_string(response).strip().lower()
    if not content:
        logger.warning(
            "Search flow classification returned empty response; defaulting to chat flow."
        )
        return False

    # Prefer chat if both appear.
    if CHAT_CLASS in content:
        return False
    if SEARCH_CLASS in content:
        return True

    logger.warning(
        "Search flow classification returned unexpected response; defaulting to chat flow. Response=%r",
        content,
    )
    return False
