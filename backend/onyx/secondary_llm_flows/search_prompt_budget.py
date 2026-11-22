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
        output_tokens = min(
            max_output_tokens,
            budget.max_output_tokens or max_output_tokens,
            max(1, available_tokens // 4),
        )
        self.input_tokens = min(
            max(0, llm.config.max_input_tokens - budget.safety_tokens),
            available_tokens - output_tokens,
        )
        self.token_counter = get_llm_token_counter(llm)

        self.options = GenerationOptions(
            reasoning_effort=ReasoningEffort.OFF, max_tokens=output_tokens
        )

    def fitting_prefix(
        self,
        length: int,
        build_request: Callable[[int], GenerationRequest],
        *,
        allow_slack: bool = False,
    ) -> tuple[int, GenerationRequest] | None:
        """Find a verified prefix. Text may leave 2% of the input budget unused."""

        def measure(end: int) -> tuple[GenerationRequest, int]:
            request = build_request(end)
            return request, self.token_counter(
                request.model_dump_json(exclude_none=True)
            )

        request, full = measure(length)
        if full <= self.input_tokens:
            return length, request
        best, empty = measure(0)
        if empty > self.input_tokens:
            return None
        lower, upper = 0, length
        # Start at the observed token density, then bisect if the prefix differs.
        probe = (self.input_tokens - empty) * length // (full - empty)
        while upper - lower > 1:
            probe = max(lower + 1, min(probe, upper - 1))
            request, tokens = measure(probe)
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
