from collections.abc import Callable

from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.llm.models import GenerationOptions, GenerationRequest, ReasoningEffort
from onyx.llm.token_budget import resolve_token_budget


class SearchPromptBudget:
    def __init__(self, llm: LLM, max_output_tokens: int = 4096) -> None:
        budget = resolve_token_budget(llm)
        available_tokens = llm.config.max_input_tokens
        if budget.context_tokens is not None:
            available_tokens = min(
                available_tokens, budget.context_tokens - budget.safety_tokens
            )
        # Completion limits include reasoning before the visible utility response.
        self.output_tokens = min(
            max_output_tokens,
            budget.max_output_tokens or max_output_tokens,
            max(1, available_tokens // 4),
        )
        self.input_tokens = min(
            max(0, llm.config.max_input_tokens - budget.safety_tokens),
            available_tokens - self.output_tokens,
        )
        self.token_counter = get_llm_token_counter(llm)

    def options(self) -> GenerationOptions:
        return GenerationOptions(
            reasoning_effort=ReasoningEffort.OFF, max_tokens=self.output_tokens
        )

    def fits(self, request: GenerationRequest) -> bool:
        return (
            self.token_counter(request.model_dump_json(exclude_none=True))
            <= self.input_tokens
        )

    def fit_text(
        self, text: str, build_request: Callable[[str], GenerationRequest]
    ) -> str | None:
        if self.fits(build_request(text)):
            return text
        if not self.fits(build_request("")):
            return None
        lower, upper = 0, len(text)
        while lower < upper:
            middle = (lower + upper + 1) // 2
            if self.fits(build_request(text[:middle])):
                lower = middle
            else:
                upper = middle - 1
        return text[:lower]
