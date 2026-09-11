from onyx.chat.models import LlmStepResult
from onyx.llm.constants import LlmProviderNames
from onyx.llm.exceptions import ClassifiedLLMError
from onyx.llm.interfaces import LLM, ToolChoiceOptions
from onyx.llm.model_capabilities import is_true_openai_model


class EmptyLLMResponseError(ClassifiedLLMError):
    """Raised when the streamed LLM response completes without a usable answer."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        tool_choice: ToolChoiceOptions,
        client_error_msg: str,
        error_code: str = "EMPTY_LLM_RESPONSE",
        is_retryable: bool = True,
        finish_reason: str | None = None,
    ) -> None:
        super().__init__(
            client_error_msg=client_error_msg,
            error_code=error_code,
            is_retryable=is_retryable,
        )
        self.provider = provider
        self.model = model
        self.tool_choice = tool_choice
        self.finish_reason = finish_reason


# LiteLLM maps these native policy blocks to content_filter, but gateways may
# forward the provider value unchanged.
_REFUSAL_FINISH_REASONS = {
    "BLOCKLIST",
    "CONTENT_BLOCKED",
    "ERROR_TOXIC",
    "IMAGE_OTHER",
    "IMAGE_PROHIBITED_CONTENT",
    "IMAGE_RECITATION",
    "IMAGE_SAFETY",
    "LANGUAGE",
    "MODEL_ARMOR",
    "OTHER",
    "PROHIBITED_CONTENT",
    "RECITATION",
    "SAFETY",
    "SPII",
    "content_filter",
    "content_filtered",
    "guardrail_intervened",
    "refusal",
    "sensitive",
}


def build_empty_llm_response_error(
    llm: LLM,
    llm_step_result: LlmStepResult,
    tool_choice: ToolChoiceOptions,
) -> EmptyLLMResponseError:
    provider = llm.config.model_provider
    model = llm.config.model_name
    finish_reason = llm_step_result.finish_reason

    # A refusal/content-filter stop is a deliberate model decision (HTTP 200
    # with no content), not a transport failure — retrying the same request
    # against the same model will not help.
    if finish_reason in _REFUSAL_FINISH_REASONS:
        model_suggestion = (
            " (e.g. Claude Opus 4.8)" if provider == LlmProviderNames.ANTHROPIC else ""
        )
        return EmptyLLMResponseError(
            provider=provider,
            model=model,
            tool_choice=tool_choice,
            client_error_msg=(
                "The selected model declined to respond to this request and "
                f"returned no content (finish_reason={finish_reason}). Try "
                "rephrasing the request or switching to a different model"
                f"{model_suggestion}."
            ),
            error_code="MODEL_REFUSAL",
            is_retryable=False,
            finish_reason=finish_reason,
        )

    # OpenAI quota exhaustion has reached us as a streamed "stop" with zero content.
    # When the stream is completely empty and there is no reasoning/tool output, surface
    # the likely account-level cause instead of a generic tool-calling error.
    if (
        not llm_step_result.reasoning
        and provider == LlmProviderNames.OPENAI
        and is_true_openai_model(provider, model)
    ):
        return EmptyLLMResponseError(
            provider=provider,
            model=model,
            tool_choice=tool_choice,
            client_error_msg=(
                "The selected OpenAI model returned an empty streamed response "
                "before producing any tokens. This commonly happens when the API "
                "key or project has no remaining quota or billing is not enabled. "
                "Verify quota and billing for this key and try again."
            ),
            error_code="BUDGET_EXCEEDED",
            is_retryable=False,
            finish_reason=finish_reason,
        )

    return EmptyLLMResponseError(
        provider=provider,
        model=model,
        tool_choice=tool_choice,
        client_error_msg=(
            "The selected model returned no final answer before the stream "
            "completed. No text or tool calls were received from the upstream "
            "provider."
        ),
        finish_reason=finish_reason,
    )
