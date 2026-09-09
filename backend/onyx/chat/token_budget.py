from dataclasses import dataclass

from onyx.configs.model_configs import (
    GEN_AI_INPUT_TOKEN_SAFETY_MARGIN,
    GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
)
from onyx.llm.interfaces import LLM
from onyx.llm.model_capabilities import (
    find_model_obj,
    get_model_map,
    model_identity_names,
)


@dataclass(frozen=True)
class ChatTokenBudget:
    input_tokens: int
    max_output_tokens: int | None
    context_tokens: int | None
    safety_tokens: int

    def output_allowance(self, estimated_input_tokens: int) -> int | None:
        if self.max_output_tokens is None or self.context_tokens is None:
            return None
        if estimated_input_tokens < 0:
            raise ValueError("estimated_input_tokens must be non-negative")

        available_output_tokens = (
            self.context_tokens - self.safety_tokens - estimated_input_tokens
        )
        if available_output_tokens < min(
            self.max_output_tokens, max(1, GEN_AI_NUM_RESERVED_OUTPUT_TOKENS)
        ):
            return None

        return min(self.max_output_tokens, available_output_tokens)


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def resolve_chat_token_budget(llm: LLM) -> ChatTokenBudget:
    config = llm.config
    raw_input_tokens = max(0, config.max_input_tokens)
    input_tokens = max(
        0, int(raw_input_tokens * (1 - GEN_AI_INPUT_TOKEN_SAFETY_MARGIN))
    )
    safety_tokens = raw_input_tokens - input_tokens
    model_map = get_model_map()
    for model_name in model_identity_names(config.model_name, config.deployment_name):
        model_obj = find_model_obj(model_map, config.model_provider, model_name) or {}
        model_input = _positive_int(model_obj.get("max_input_tokens"))
        model_output = _positive_int(model_obj.get("max_output_tokens"))
        if model_input is not None and model_output is not None:
            context_tokens = (
                _positive_int(model_obj.get("max_context_tokens")) or model_input
            )
            reserved_input = min(
                raw_input_tokens, model_input, context_tokens - model_output
            )
            if reserved_input <= 0:
                break
            input_tokens = max(
                0, int(reserved_input * (1 - GEN_AI_INPUT_TOKEN_SAFETY_MARGIN))
            )
            return ChatTokenBudget(
                input_tokens=input_tokens,
                max_output_tokens=model_output,
                context_tokens=context_tokens,
                safety_tokens=reserved_input - input_tokens,
            )
    return ChatTokenBudget(input_tokens, None, None, safety_tokens)
