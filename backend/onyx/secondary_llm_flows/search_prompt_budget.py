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

    def _size(self, request: GenerationRequest) -> int:
        return self.token_counter(request.model_dump_json(exclude_none=True))

    def fits(self, request: GenerationRequest) -> bool:
        return self._size(request) <= self.input_tokens

    def fitting_prefix(
        self,
        length: int,
        build_request: Callable[[int], GenerationRequest],
        *,
        allow_slack: bool = False,
    ) -> tuple[int, GenerationRequest] | None:
        """Find a verified prefix. Text may leave 2% of the input budget unused."""

        request = build_request(length)
        full = self._size(request)
        if full <= self.input_tokens:
            return length, request
        best = build_request(0)
        empty = self._size(best)
        if empty > self.input_tokens:
            return None
        lower, upper = 0, length
        # Start at the observed token density, then bisect if the prefix differs.
        probe = (self.input_tokens - empty) * length // (full - empty)
        while upper - lower > 1:
            probe = max(lower + 1, min(probe, upper - 1))
            request = build_request(probe)
            tokens = self._size(request)
            if tokens <= self.input_tokens:
                lower, best = probe, request
                if (
                    allow_slack
                    and (tokens - empty) * 100 >= (self.input_tokens - empty) * 98
                ):
                    break
            else:
                upper = probe
            probe = (lower + upper) // 2
        return lower, best

    def fit_text(
        self, text: str, build_request: Callable[[str], GenerationRequest]
    ) -> GenerationRequest | None:
        fit = self.fitting_prefix(
            len(text), lambda end: build_request(text[:end]), allow_slack=True
        )
        return fit[1] if fit is not None else None
