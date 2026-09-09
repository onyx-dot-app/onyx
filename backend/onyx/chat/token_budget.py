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
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _safe_input_tokens(raw_input_tokens: int) -> tuple[int, int]:
    raw_input_tokens = max(0, raw_input_tokens)
    safe_input_tokens = int(raw_input_tokens * (1 - GEN_AI_INPUT_TOKEN_SAFETY_MARGIN))
    safe_input_tokens = max(0, safe_input_tokens)
    return safe_input_tokens, raw_input_tokens - safe_input_tokens


def _legacy_chat_token_budget(llm: LLM) -> ChatTokenBudget:
    safe_input_tokens, safety_tokens = _safe_input_tokens(llm.config.max_input_tokens)
    return ChatTokenBudget(
        input_tokens=safe_input_tokens,
        max_output_tokens=None,
        context_tokens=None,
        safety_tokens=safety_tokens,
    )


def _find_model_budget_metadata(llm: LLM) -> dict[str, object] | None:
    model_map = get_model_map()
    for model_name in model_identity_names(
        llm.config.model_name, llm.config.deployment_name
    ):
        model_obj = find_model_obj(
            model_map=model_map,
            provider=llm.config.model_provider,
            model_name=model_name,
        )
        if (
            model_obj is not None
            and _positive_int(model_obj.get("max_input_tokens")) is not None
            and _positive_int(model_obj.get("max_output_tokens")) is not None
        ):
            return model_obj
    return None


def resolve_chat_token_budget(llm: LLM) -> ChatTokenBudget:
    model_obj = _find_model_budget_metadata(llm)
    if model_obj is None:
        return _legacy_chat_token_budget(llm)

    model_input_tokens = _positive_int(model_obj.get("max_input_tokens"))
    model_output_tokens = _positive_int(model_obj.get("max_output_tokens"))
    if model_input_tokens is None or model_output_tokens is None:
        return _legacy_chat_token_budget(llm)

    model_context_tokens = (
        _positive_int(model_obj.get("max_context_tokens")) or model_input_tokens
    )
    safe_input_tokens, safety_tokens = _safe_input_tokens(llm.config.max_input_tokens)
    return ChatTokenBudget(
        input_tokens=safe_input_tokens,
        max_output_tokens=model_output_tokens,
        context_tokens=model_context_tokens,
        safety_tokens=safety_tokens,
    )
