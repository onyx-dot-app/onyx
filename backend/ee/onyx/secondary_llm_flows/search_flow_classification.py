from ee.onyx.prompts.search_flow_classification import (
    CHAT_CLASS,
    SEARCH_CHAT_PROMPT,
    SEARCH_CLASS,
)
from onyx.llm.interfaces import LLM, GenerationContext
from onyx.llm.models import (
    GenerationOptions,
    GenerationRequest,
    Message,
    ReasoningEffort,
    UserMessage,
)
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


@log_function_time(print_only=True)
def classify_is_search_flow(
    query: str,
    llm: LLM,
) -> bool:
    messages: list[Message] = [
        UserMessage(content=SEARCH_CHAT_PROMPT.format(user_query=query))
    ]
    response = llm.invoke(
        GenerationRequest(
            messages=messages,
            options=GenerationOptions(
                reasoning_effort=ReasoningEffort.OFF, max_tokens=20
            ),
        ),
        context=GenerationContext(timeout=2, flow=LLMFlow.SEARCH_FLOW_CLASSIFICATION),
    )

    content = response.text.strip().lower()
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
