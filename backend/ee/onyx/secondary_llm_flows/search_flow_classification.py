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
from onyx.secondary_llm_flows.search_prompt_budget import SearchPromptBudget
from onyx.tracing.flows import LLMFlow
from onyx.utils.logger import setup_logger
from onyx.utils.timing import log_function_time

logger = setup_logger()


@log_function_time()
def classify_is_search_flow(
    query: str,
    llm: LLM,
    enforce_llm_input_budget: bool = False,
) -> bool:
    messages: list[Message] = [
        UserMessage(content=SEARCH_CHAT_PROMPT.format(user_query=query))
    ]
    budget = SearchPromptBudget(llm) if enforce_llm_input_budget else None
    request = GenerationRequest(
        messages=messages,
        options=(
            budget.options()
            if budget
            else GenerationOptions(reasoning_effort=ReasoningEffort.OFF, max_tokens=20)
        ),
    )
    if budget and not budget.fits(request):
        logger.warning("Search classification prompt exceeds its input budget")
        return False
    response = llm.invoke(
        request,
        # Classification blocks the next UI action, so keep the timeout short.
        context=GenerationContext(
            total_timeout_s=2, flow=LLMFlow.SEARCH_FLOW_CLASSIFICATION
        ),
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
